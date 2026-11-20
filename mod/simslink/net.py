"""后台线程：只跟本机的小转发程序说话，绝不碰游戏对象。

出去的（状态 / 事件 / 指令结果）和进来的（AI 的指令）都走同一个请求：
POST /sims/mod/sync  ->  {"commands": [...]}
"""
import http.client
import json
import queue
import threading
import time

from simslink import log

_OUT_CAP = 300


class Link(object):
    def __init__(self, port):
        self.port = int(port)
        self.inbox = queue.Queue()        # AI 的指令，等游戏线程来取
        self._lock = threading.Lock()
        self._events = []
        self._results = []
        self._state = None                # 最新一张状态；发出去就清掉
        self._after = 0                   # 已经收到的最后一条指令号
        self._thread = None
        self.connected = False
        self.last_ok = 0.0
        self.last_error = ''
        self.active = False               # 有没有存档在跑；没有就慢一点敲门
        self._owed = 0                    # 刚领走、还没交结果的指令数
        self.screen = None                # 玩家在哪个界面（live/build/cas/loading/away），每趟都带上

    # ---- 游戏线程调用 ----
    def push_state(self, state):
        with self._lock:
            self._state = state

    def push_event(self, event):
        with self._lock:
            self._events.append(event)
            del self._events[:-_OUT_CAP]

    def push_result(self, result):
        with self._lock:
            self._results.append(result)
            del self._results[:-_OUT_CAP]

    def local(self, path, payload, timeout=30):
        """问本机的小转发程序一件它自己能办的事（拍照、发截图），不经过服务器。
        会等，所以只能在后台线程里调，绝不能在游戏线程上调。"""
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout)
        try:
            conn.request('POST', path, body=data,
                         headers={'Content-Type': 'application/json', 'Content-Length': str(len(data)),
                                  'Connection': 'close'})
            resp = conn.getresponse()
            raw = resp.read()
            if resp.status != 200:
                # 旧版转发程序不认识 /local/：它会回 404
                return {'ok': False, 'text': '电脑上的小转发程序是旧版，不认识这个请求。换上新的 SimsLinkBridge。'}
            return json.loads(raw.decode('utf-8'))
        except Exception as exc:
            return {'ok': False, 'text': '问不到小转发程序：%s' % exc}
        finally:
            conn.close()

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name='SimsLinkNet')
        self._thread.daemon = True
        self._thread.start()

    # ---- 后台线程 ----
    def _take(self):
        with self._lock:
            body = {'v': 1, 'after': self._after, 'events': self._events, 'results': self._results}
            if self._state is not None:
                body['state'] = self._state
            if self.screen:
                body['screen'] = self.screen
            self._events, self._results, self._state = [], [], None
        return body

    def _put_back(self, body):
        with self._lock:
            self._events = (body.get('events') or []) + self._events
            self._results = (body.get('results') or []) + self._results
            del self._events[:-_OUT_CAP]
            del self._results[:-_OUT_CAP]
            if self._state is None and body.get('state') is not None:
                self._state = body['state']

    def _post(self, body):
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        try:
            conn.request('POST', '/sims/mod/sync', body=data,
                         headers={'Content-Type': 'application/json', 'Content-Length': str(len(data)),
                                  'Connection': 'close'})
            resp = conn.getresponse()
            raw = resp.read()
            if resp.status != 200:
                raise RuntimeError('HTTP %s %s' % (resp.status, raw[:200].decode('utf-8', 'replace')))
            return json.loads(raw.decode('utf-8'))
        finally:
            conn.close()

    def _wait_for_results(self):
        """刚领了指令：等游戏线程做完再敲门，结果就能跟着这一趟回去，不用多等一轮。"""
        if self._owed <= 0:
            return
        deadline = time.time() + 1.5
        while time.time() < deadline:
            with self._lock:
                if len(self._results) >= self._owed:
                    break
            time.sleep(0.02)
        self._owed = 0

    def _run(self):
        fails = 0
        while True:
            self._wait_for_results()
            body = self._take()
            has_news = bool(body['events'] or body['results'] or 'state' in body)
            if not self.active and not has_news:
                body['wait'] = 0
            else:
                body['wait'] = 2
            try:
                reply = self._post(body)
            except Exception as exc:
                self._put_back(body)
                self.connected = False
                self.last_error = '%s: %s' % (type(exc).__name__, exc)
                fails += 1
                if fails == 1:
                    log.warn('连不上小转发程序（%s）。它开着吗？' % self.last_error)
                time.sleep(min(15, 2 + fails))
                continue
            if fails or not self.connected:
                log.info('连上小转发程序了')
                try:
                    hello = self.local('/local/hello', {'dir': log.sims_dir()}, timeout=5)
                    log.info('转发程序版本：%s' % (hello.get('text') if hello.get('ok') else '旧版（不会拍照）'))
                except Exception:
                    pass
            fails = 0
            self.connected = True
            self.last_ok = time.time()
            self.last_error = ''
            for cmd in (reply or {}).get('commands') or []:
                try:
                    cid = int(cmd.get('id') or 0)
                except Exception:
                    continue
                if cid > self._after:
                    self._after = cid
                    self._owed += 1
                    self.inbox.put(cmd)
            if not self.active:
                time.sleep(8)
            elif not has_news and not (reply or {}).get('commands'):
                time.sleep(0.2)
