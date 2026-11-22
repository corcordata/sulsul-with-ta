import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sulsul_server import core  # noqa: E402


@pytest.fixture(autouse=True)
def _wired():
    """下面大多数测试写的是「回话已经接进 /sims/reply」的那种接法；没接的那种在最后单独测。"""
    core.SETTINGS.mirror, core.SETTINGS.pronoun = True, "她"
    yield
    core.SETTINGS.mirror, core.SETTINGS.pronoun = False, "她"

STATE = {
    "zone": {"lot": "柳溪小屋", "home": True},
    "clock": {"day": 3, "hour": 14, "minute": 5, "speed": "NORMAL"},
    "sims": [
        {"name": "阿澈", "here": True, "his": True, "mood": {"name": "Flirty", "level": 2},
         "motives": {"Hunger": -60, "Energy": 40}, "doing": [{"name": "sofa_Sit", "target": "object_Sofa"}],
         "queue": [{"name": "mixer_social_Kiss", "target": "小椴"}], "near": ["小椴"],
         "rel": {"小椴": {"friend": 80, "romance": 100, "bits": ["romantic-Married"]}}},
        {"name": "小椴", "here": True, "active": True, "pregnant": True, "doing": []},
        {"name": "团子", "here": False},
    ],
    "others": ["路人甲"],
}


def test_clean_sync_rejects_garbage_and_clamps_wait():
    with pytest.raises(ValueError):
        core.clean_sync([])
    with pytest.raises(ValueError):
        core.clean_sync({"state": "x"})
    sync = core.clean_sync({"after": "7", "wait": 99, "events": [{"t": "say", "text": " 你在哪 "}, "junk"],
                                 "results": [{"id": 1, "ok": True}, {"ok": True}]})
    assert sync["after"] == 7 and sync["wait"] == 5.0
    assert sync["events"] == [{"t": "say", "text": "你在哪"}]
    assert sync["results"] == [{"id": 1, "ok": True}]
    assert sync["screen"] is None
    assert core.clean_sync({"screen": "cas"})["screen"] == "cas"
    assert core.clean_sync({"screen": "hacked"})["screen"] is None


def test_record_and_format_now(tmp_path):
    core.record(tmp_path, core.clean_sync({"state": STATE, "events": [{"t": "say", "text": "在吗"}]}), now=1000)
    assert core.is_live(tmp_path, now=1010)
    assert not core.is_live(tmp_path, now=1000 + core.LIVE_SECONDS + 1)
    text = core.format_now(tmp_path, now=1010)
    assert "连着" in text and "柳溪小屋（自己家）" in text and "周三 14:05" in text
    assert "阿澈（你）：心情 调情 2｜在 sofa_Sit → object_Sofa｜排队 mixer_social_Kiss → 小椴｜告急 饿 -60｜身边 小椴" in text
    assert "小椴（她正点着的）：闲着｜怀孕中" in text
    assert "团子：不在这块地上" in text
    assert "你和小椴：友情 80｜恋爱 100｜romantic-Married" in text
    assert "这一带的别人（街上路过的也算在里面，不一定在你们身边）：路人甲" in text
    assert "她在游戏里说：「在吗」" in text
    stale = core.format_now(tmp_path, now=1000 + 600)
    assert "没连着（上次 10 分钟前）" in stale


def test_format_now_before_first_contact(tmp_path):
    assert "还没连上过" in core.format_now(tmp_path)


def test_events_are_trimmed(tmp_path):
    for i in range(core.EVENTS_KEEP * 2 + 5):
        core.record(tmp_path, {"events": [{"t": "act", "who": "阿澈", "name": f"a{i}"}]}, now=i)
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= core.EVENTS_KEEP * 2
    assert core.recent_events(tmp_path, 3)[-1]["name"] == f"a{core.EVENTS_KEEP * 2 + 4}"


def test_clean_command():
    assert core.clean_command({"op": "say", "args": {"text": "过来", "reply": True, "who": None}}) == {
        "op": "say", "args": {"text": "过来", "reply": True}}
    for bad in ({"op": "run_python"}, {"op": "say", "args": {}}, {"op": "do", "args": {"target": "小椴"}},
                {"op": "speed", "args": {"speed": "9"}}, {"op": "list", "args": "x"}):
        with pytest.raises(ValueError):
            core.clean_command(bad)


def test_command_ids_and_expiry():
    first = core.next_command_id(0, now=10.0)
    assert first == 10000
    assert core.next_command_id(first, now=10.0) == first + 1
    commands = [{"id": 5, "op": "look", "args": {}, "at": 100.0}, {"id": 9, "op": "do", "args": {}, "at": 130.0}]
    assert [c["id"] for c in core.pending_commands(commands, after=0, now=131)] == [9]
    assert core.pending_commands(commands, after=9, now=131) == []
    assert [c["id"] for c in core.prune_commands(commands, now=131)] == [9]


def test_note_for_him_keeps_her_words_out_of_it():
    note = core.tell_him_note("〔Sims 4 · 连着，她正在玩〕\n地点：柳溪小屋")
    assert "自动弹在她游戏右上角" in note and "地点：柳溪小屋" in note
    assert "看得见吗" not in note          # 她说的那句不在注解里，气泡和注解各管各的


def test_tell_him_text_points_at_the_tool():
    text = core.tell_him_text("你在干嘛", core.tell_him_note("〔Sims 4 · 连着，她正在玩〕"))
    assert "「你在干嘛」" in text and "自动弹在她游戏右上角" in text
    assert core.her_says({"events": [{"t": "say", "text": "a"}, {"t": "act"}, {"t": "say", "text": ""}]}) == ["a"]


def test_screens_change_the_head_and_block_actions(tmp_path):
    core.record(tmp_path, core.clean_sync({"state": STATE, "screen": "live"}), now=1000)
    assert core.screen(tmp_path) == "live"
    assert "连着，她正在玩" in core.format_now(tmp_path, now=1001)
    assert core.blocked_reason(tmp_path, "do") == ""

    core.record(tmp_path, core.clean_sync(
        {"screen": "cas", "events": [{"t": "screen", "screen": "cas"}]}), now=1010)
    text = core.format_now(tmp_path, now=1011)
    assert "连着｜她在捏人界面" in text and "进去之前的样子" in text
    assert "阿澈（你）" in text                      # 进去之前那张还在
    assert "她进了捏人界面" in text
    assert "捏人界面" in core.blocked_reason(tmp_path, "do")
    assert core.blocked_reason(tmp_path, "list") != ""
    assert core.blocked_reason(tmp_path, "say") == ""   # 说话不拦

    # 一趟没带 screen（比如只交结果）：记着上一次的，不退回 live
    core.record(tmp_path, core.clean_sync({"results": [{"id": 3, "ok": True}]}), now=1012)
    assert core.screen(tmp_path) == "cas"

    core.record(tmp_path, core.clean_sync({"screen": "build"}), now=1020)
    assert "建造模式" in core.format_now(tmp_path, now=1021)
    assert core.blocked_reason(tmp_path, "do") == ""    # 建造模式不拦，游戏自己会回话

    core.record(tmp_path, core.clean_sync(
        {"screen": "live", "events": [{"t": "screen", "screen": "live"}]}), now=1030)
    text = core.format_now(tmp_path, now=1031)
    assert "连着，她正在玩" in text and "她回到游戏里了" in text


def test_old_mod_without_screen_still_reads_as_playing(tmp_path):
    core.record(tmp_path, core.clean_sync({"state": STATE}), now=1000)
    assert core.screen(tmp_path) == "live"
    assert "连着，她正在玩" in core.format_now(tmp_path, now=1001)
    assert core.format_event({"t": "left"}) != ""


def test_note_for_him_sends_full_once_then_only_what_changed(tmp_path):
    import copy
    core.record(tmp_path, core.clean_sync({"state": STATE, "screen": "live"}), now=1000)
    first = core.note_for_him(tmp_path, now=1001)
    assert "连着，她正在玩" in first and "阿澈（你）" in first and "这一带的别人" in first
    assert "自动弹在她游戏右上角" in first

    # 紧接着又说一句，游戏里什么都没变：一行就够
    same = core.note_for_him(tmp_path, now=1005)
    assert "跟上一句时一样" in same and "周三 14:05" in same
    assert "阿澈（你）" not in same and len(same) < len(first) / 2

    # 只有时间往前走：不算变
    later = copy.deepcopy(STATE)
    later["clock"]["minute"] = 20
    core.record(tmp_path, core.clean_sync({"state": later}), now=1010)
    assert "跟上一句时一样" in core.note_for_him(tmp_path, now=1011)

    # 她的小人去睡了，还发生了一件事：只列她那一行和那件事
    moved = copy.deepcopy(later)
    moved["sims"][1]["doing"] = [{"name": "bed_Sleep", "target": "object_Bed"}]
    core.record(tmp_path, core.clean_sync({"state": moved, "events": [
        {"t": "act", "who": "小椴", "name": "bed_Sleep", "target": "object_Bed"},
        {"t": "say", "text": "晚安"}]}), now=1020)
    delta = core.note_for_him(tmp_path, now=1021)
    assert "只列变了的" in delta and "小椴（她正点着的）：在 bed_Sleep → object_Bed" in delta
    assert "阿澈（你）" not in delta and "这一带的别人" not in delta
    assert "小椴 开始 bed_Sleep" in delta and "晚安" not in delta   # 她说的话他已经当消息收到了

    # 她进了捏人界面：界面变了，重新给完整的
    core.record(tmp_path, core.clean_sync({"screen": "cas"}), now=1030)
    cas = core.note_for_him(tmp_path, now=1031)
    assert "她在捏人界面" in cas and "阿澈（你）" in cas

    # 隔了十分钟以上：重新给完整的
    core.record(tmp_path, core.clean_sync({"state": moved}), now=1040 + core.TOLD_TTL)
    again = core.note_for_him(tmp_path, now=1041 + core.TOLD_TTL)
    assert "阿澈（你）" in again and "这一带的别人" in again


def test_look_is_always_the_full_picture(tmp_path):
    core.record(tmp_path, core.clean_sync({"state": STATE, "screen": "live"}), now=1000)
    core.note_for_him(tmp_path, now=1001)
    core.note_for_him(tmp_path, now=1002)
    assert "阿澈（你）" in core.format_now(tmp_path, now=1003)


def test_photo_command_and_events():
    assert core.clean_command({"op": "photo", "args": {"text": "刚出浴"}}) == {"op": "photo", "args": {"text": "刚出浴"}}
    assert core.clean_command({"op": "photo"}) == {"op": "photo", "args": {}}
    assert "你拍了一张照片" in core.format_event({"t": "photo", "by": "him"})
    assert "3 张游戏截图" in core.format_event({"t": "photo", "by": "her", "count": 3})


def test_photo_query_is_cleaned():
    assert core.clean_photo_query("him", " 看这个 ", "1763", "") == {
        "by": "him", "caption": "看这个", "shot": 1763, "hold": False}
    assert core.clean_photo_query("her", "", "abc", "1") == {"by": "her", "caption": "", "shot": 0, "hold": True}
    with pytest.raises(ValueError):
        core.clean_photo_query("someone", "", "", "")


def test_shrink_photo_makes_a_small_jpeg_and_rejects_non_images():
    import io

    Image = pytest.importorskip("PIL.Image")
    big = io.BytesIO()
    Image.new("RGB", (2560, 1440), (240, 200, 90)).save(big, format="PNG")
    out = core.shrink_photo(big.getvalue())
    small = Image.open(io.BytesIO(out))
    assert small.format == "JPEG" and max(small.size) == core.PHOTO_EDGE
    for junk in (b"", b"not an image at all", b"MZ" + b"\x00" * 200):
        with pytest.raises(ValueError):
            core.shrink_photo(junk)


def test_others_split_into_on_lot_and_street(tmp_path):
    """0.2.2 起 mod 把「别人」拆开报：这块地上的，和街上路过的。路人不该被读成围观的。"""
    import copy
    state = copy.deepcopy(STATE)
    state["others"] = ["菲尔斯莫拉"]
    state["street"] = {"n": 8, "names": ["Tom", "贝拉", "路人甲"]}
    core.record(tmp_path, core.clean_sync({"state": state, "screen": "live"}), now=1000)
    text = core.format_now(tmp_path, now=1001)
    assert "这块地上的别人：菲尔斯莫拉" in text
    assert "街上路过的（不在这块地上，只是游戏载入的路人）：8 人，有 Tom、贝拉、路人甲等" in text
    assert "这一带的别人" not in text
    first = core.note_for_him(tmp_path, now=1002)
    assert "街上路过的" in first

    # 街上的人来来去去不算「变了」：不然她每说一句都要重念一遍路人
    walked = copy.deepcopy(state)
    walked["street"] = {"n": 3, "names": ["Tom"]}
    core.record(tmp_path, core.clean_sync({"state": walked}), now=1010)
    assert "跟上一句时一样" in core.note_for_him(tmp_path, now=1011)

    # 有人真走进这块地：要告诉他
    came = copy.deepcopy(walked)
    came["others"] = ["菲尔斯莫拉", "Tom"]
    core.record(tmp_path, core.clean_sync({"state": came}), now=1020)
    delta = core.note_for_him(tmp_path, now=1021)
    assert "这块地上的别人：菲尔斯莫拉、Tom" in delta and "街上路过的" not in delta

    # 一个外人都没有，也明说
    alone = copy.deepcopy(state)
    alone["others"] = []
    alone["street"] = {"n": 0, "names": []}
    core.record(tmp_path, core.clean_sync({"state": alone}), now=1030)
    text = core.format_now(tmp_path, now=1031)
    assert "这块地上没有别的小人" in text and "街上路过的" not in text


# ───────────────────────── 游戏叫醒他 ─────────────────────────

HOME = {
    "zone": {"lot": "柳溪小屋", "home": True},
    "clock": {"day": 3, "hour": 14, "minute": 5},
    "sims": [
        {"name": "阿澈", "here": True, "his": True, "doing": [], "near": ["小椴"],
         "rel": {"小椴": {"friend": 80, "romance": 100, "bits": ["romantic-Engaged"]}}},
        {"name": "小椴", "here": True, "hers": True, "active": True, "doing": [], "motives": {"Hunger": -20}},
    ],
    "others": ["Tom"],
    "street": {"n": 2, "names": ["贝拉", "路人甲"]},
}


def _sync(tmp_path, now, state=None, events=(), screen="live"):
    """照 app.py 的顺序走一趟：先问要不要叫他，再存，再拼字。回叫他的那段字（不叫就是空的）。"""
    sync = core.clean_sync({"state": state, "events": list(events), "screen": screen})
    plan = core.wake_plan(tmp_path, sync, now=now)
    core.record(tmp_path, sync, now=now)
    return core.wake_text(tmp_path, plan, now=now) if plan else ""


def test_wake_when_her_sim_is_kissed_by_someone_else(tmp_path):
    assert _sync(tmp_path, 1000, HOME) == ""                      # 平平常常：不叫
    text = _sync(tmp_path, 1010, HOME, [{"t": "act", "who": "小椴", "name": "mixer_social_Kiss_targeted_romance", "target": "Tom"}])
    assert text.startswith("🏠 [Sims 4·游戏叫你]")
    assert "小椴 开始 mixer_social_Kiss_targeted_romance → Tom（Tom 不是你）" in text
    assert "自动弹在她游戏右上角" in text and "阿澈（你）" in text   # 头一回叫：带完整的一张
    # 同一个人十分钟内不为这事叫第二次；而且两次叫醒之间本来就要隔五分钟
    again = [{"t": "act", "who": "小椴", "name": "mixer_social_Flirt", "target": "Tom"}]
    assert _sync(tmp_path, 1100, HOME, again) == ""
    assert _sync(tmp_path, 1010 + 400, HOME, again) == ""         # 过了五分钟，但还在十分钟里
    assert "Tom" in _sync(tmp_path, 1010 + 700, HOME, again)


def test_wake_not_for_kissing_him_or_for_objects(tmp_path):
    _sync(tmp_path, 1000, HOME)
    assert _sync(tmp_path, 1010, HOME, [{"t": "act", "who": "小椴", "name": "mixer_social_Kiss_targeted_romance", "target": "阿澈"}]) == ""
    assert _sync(tmp_path, 1020, HOME, [{"t": "act", "who": "小椴", "name": "fridge_Cook", "target": "object_Fridge"}]) == ""
    assert _sync(tmp_path, 1030, HOME, [{"t": "act", "who": "小椴", "name": "sim_Chat", "target": "Tom"}]) == ""


def test_wake_for_sex_on_furniture_only_if_he_is_not_the_one(tmp_path):
    """WW 的动作目标是家具不是人：他自己也在做就没事；他没在做、她身边有外人，才叫。"""
    import copy
    both = copy.deepcopy(HOME)
    both["sims"][0]["doing"] = [{"name": "TURBODRIVER:WickedWhims_Sex_Animation_Default"}]
    _sync(tmp_path, 1000, both)
    act = [{"t": "act", "who": "小椴", "name": "TURBODRIVER:WickedWhims_Sex_Animation_Default", "target": "object_fridge"}]
    assert _sync(tmp_path, 1010, both, act) == ""
    alone = copy.deepcopy(HOME)
    alone["sims"][1]["near"] = ["Tom"]
    text = _sync(tmp_path, 1020, alone, act)
    assert "身边是 Tom，不是你" in text


def test_wake_when_his_own_sim_strays(tmp_path):
    _sync(tmp_path, 1000, HOME)
    text = _sync(tmp_path, 1010, HOME, [{"t": "act", "who": "阿澈", "name": "mixer_social_Flirt_targeted", "target": "贝拉"}])
    assert "你的小人自己去 mixer_social_Flirt_targeted → 贝拉 了（不是你点的" in text


def test_wake_big_things_skip_the_five_minute_gap(tmp_path):
    _sync(tmp_path, 1000, HOME)
    assert "Tom" in _sync(tmp_path, 1010, HOME, [{"t": "act", "who": "小椴", "name": "social_Kiss_romance", "target": "Tom"}])
    text = _sync(tmp_path, 1100, HOME, [{"t": "pregnant", "who": "小椴", "on": True}])
    assert "小椴 怀孕了" in text
    assert "只列变了的" in text or "跟上一句时一样" in text          # 刚给过完整的，这回只给变了的
    assert _sync(tmp_path, 1110, HOME, [{"t": "fire", "on": True}]) == ""      # 大事之间也隔 45 秒
    assert "着火了" in _sync(tmp_path, 1160, HOME, [{"t": "fire", "on": True}])
    assert "小椴 去世了" in _sync(tmp_path, 1300, HOME, [{"t": "death", "who": "小椴"}])
    assert _sync(tmp_path, 1400, HOME, [{"t": "fire", "on": False}]) == ""     # 火灭了不叫


def test_wake_new_family_member_and_marriage(tmp_path):
    import copy
    _sync(tmp_path, 1000, HOME)
    grown = copy.deepcopy(HOME)
    grown["sims"].append({"name": "盛团子", "here": True})
    assert "家里多了一个人：盛团子" in _sync(tmp_path, 1010, grown)
    married = copy.deepcopy(grown)
    married["sims"][0]["rel"]["小椴"]["bits"] = ["romantic-Married"]
    assert "你和小椴的关系多了一条：romantic-Married" in _sync(tmp_path, 1100, married)
    # 换了一个存档（一个认识的人都没有）：不是「家里多了人」
    other = {"zone": {"lot": "别处"}, "sims": [{"name": "路人家的", "here": True}], "others": [], "street": {"n": 0}}
    assert _sync(tmp_path, 1200, other) == ""


def test_wake_when_her_need_bottoms_out_once_per_dip(tmp_path):
    import copy
    _sync(tmp_path, 1000, HOME)
    starving = copy.deepcopy(HOME)
    starving["sims"][1]["motives"] = {"Hunger": -82, "Energy": 10}
    assert "小椴 的饿掉到 -82 了" in _sync(tmp_path, 1010, starving)
    worse = copy.deepcopy(starving)
    worse["sims"][1]["motives"]["Hunger"] = -90
    assert _sync(tmp_path, 1010 + 600, worse) == ""               # 还在同一次坑里
    his = copy.deepcopy(HOME)
    his["sims"][0]["motives"] = {"Hunger": -95}                    # 他自己的小人饿了不叫
    assert _sync(tmp_path, 1010 + 1200, his) == ""


def test_wake_when_she_plays_long_without_a_word(tmp_path):
    t0 = 10_000
    _sync(tmp_path, t0, HOME)
    for step in range(1, 45 * 6):                                  # 每十秒敲一次门，四十五分钟
        assert _sync(tmp_path, t0 + step * 10, None) == "", step
    text = _sync(tmp_path, t0 + core.WAKE_IDLE + 5, None)
    assert "她已经连着玩了 45 分钟，一句话没跟你说" in text
    assert _sync(tmp_path, t0 + core.WAKE_IDLE + 600, None) == ""          # 叫过了，重新计时
    # 她说过话就重新计时
    core.record(tmp_path, core.clean_sync({"events": [{"t": "say", "text": "在吗"}]}), now=t0 + core.WAKE_IDLE + 900)
    assert _sync(tmp_path, t0 + 2 * core.WAKE_IDLE + 100, None) == ""
    # 游戏关了一阵再开：从头算
    late = t0 + 5 * core.WAKE_IDLE
    assert _sync(tmp_path, late, HOME) == ""
    assert _sync(tmp_path, late + core.WAKE_IDLE - 60, None) == ""


def test_wake_stays_quiet_when_she_is_talking_or_not_in_the_world_or_off(tmp_path):
    kiss = {"t": "act", "who": "小椴", "name": "social_Kiss_romance", "target": "Tom"}
    _sync(tmp_path, 1000, HOME)
    assert _sync(tmp_path, 1010, HOME, [kiss, {"t": "say", "text": "你看他"}]) == ""   # 她自己在说：事情跟着她那句走
    assert _sync(tmp_path, 1020, HOME, [dict(kiss, target="贝拉")], screen="cas") == ""
    core.set_wake(tmp_path, False)
    assert not core.wake_on(tmp_path)
    assert _sync(tmp_path, 1700, HOME, [dict(kiss, target="路人甲")]) == ""
    core.set_wake(tmp_path, True)
    assert "路人甲" in _sync(tmp_path, 1710, HOME, [dict(kiss, target="路人甲")])
    # 她在游戏里打 mu wake off / on：跟着事件走
    assert _sync(tmp_path, 3000, HOME, [{"t": "wake", "on": False}]) == "" and not core.wake_on(tmp_path)
    assert _sync(tmp_path, 3010, HOME, [{"t": "pregnant", "who": "小椴", "on": True}]) == ""
    assert _sync(tmp_path, 3020, HOME, [{"t": "wake", "on": True}]) == "" and core.wake_on(tmp_path)
    assert core.format_event({"t": "wake", "on": True}) == ""


def test_wake_daily_cap(tmp_path):
    _sync(tmp_path, 1000, HOME)
    woke = 0
    for n in range(core.WAKE_DAILY_MAX + 5):
        if _sync(tmp_path, 2000 + n * 60, HOME, [{"t": "death", "who": f"路人{n}"}]):   # 每次都是不同的事
            woke += 1
    assert woke == core.WAKE_DAILY_MAX


def test_new_ops_outfit_and_money():
    assert core.clean_command({"op": "outfit", "args": {}}) == {"op": "outfit", "args": {}}
    assert core.clean_command({"op": "outfit", "args": {"name": "睡衣 2"}})["args"] == {"name": "睡衣 2"}
    assert core.clean_command({"op": "money", "args": {"amount": 2000, "text": "买沙发"}})["args"] == {"amount": 2000, "text": "买沙发"}
    assert core.clean_command({"op": "money", "args": {"amount": "1500"}})["args"] == {"amount": 1500}
    for bad in (None, 0, -3, 50001, "abc"):
        with pytest.raises(ValueError):
            core.clean_command({"op": "money", "args": {"amount": bad}})


def test_state_shows_outfit_funds_fire(tmp_path):
    import copy
    state = copy.deepcopy(HOME)
    state["sims"][0]["outfit"] = "睡衣 1"
    state["funds"] = 14345
    state["fire"] = True
    core.record(tmp_path, core.clean_sync({"state": state, "screen": "live"}), now=1000)
    text = core.format_now(tmp_path, now=1001)
    assert "地点：柳溪小屋（自己家）｜周三 14:05｜家里存款 §14,345" in text
    assert "阿澈（你）：穿 睡衣 1｜闲着" in text
    assert "⚠ 这块地上着火了" in text
    assert core.format_event({"t": "fire", "on": True}) == "着火了"
    assert core.format_event({"t": "death", "who": "Tom"}) == "Tom 去世了"


def test_chinese_action_names_shown_but_matching_stays_on_internal(tmp_path):
    """mod 查到了游戏里的中文名（cn）：给他看中文；认「是不是亲热」还是靠内部名。"""
    import copy
    state = copy.deepcopy(HOME)
    state["sims"][1]["doing"] = [{"name": "mixer_social_Kiss_targeted_romance", "cn": "亲吻", "target": "Tom"}]
    assert _sync(tmp_path, 1000, HOME) == ""
    text = _sync(tmp_path, 1010, state, [{"t": "act", "who": "小椴", "name": "mixer_social_Kiss_targeted_romance",
                                          "cn": "亲吻", "target": "Tom"}])
    assert "小椴 开始 亲吻 → Tom（Tom 不是你）" in text
    assert "小椴（她，她正点着的）：在 亲吻 → Tom" in text


def test_wake_ignores_motives_added_by_other_mods(tmp_path):
    """真机上第一次叫醒他，是因为 WW 的「满足度」-100：那不是需求见底。"""
    import copy
    _sync(tmp_path, 1000, HOME)
    state = copy.deepcopy(HOME)
    state["sims"][1]["motives"] = {"TURBODRIVER:WickedWhims_Sex_Motive_Satisfaction": -100, "Hygiene": -30}
    assert _sync(tmp_path, 1010, state) == ""
    state["sims"][1]["motives"]["Hygiene"] = -80
    assert "小椴 的卫生掉到 -80 了" in _sync(tmp_path, 1020, state)


def test_playing_hint_only_while_game_is_live(tmp_path):
    assert core.playing_hint(tmp_path, now=1000) == ""
    core.record(tmp_path, core.clean_sync({"state": HOME, "screen": "live"}), now=1000)
    assert "自动弹在她游戏右上角" in core.playing_hint(tmp_path, now=1005)
    assert core.playing_hint(tmp_path, now=1000 + core.LIVE_SECONDS + 5) == ""


def test_buffs_shown_as_cards_and_time_left_is_not_a_change(tmp_path):
    """情绪状态照她在游戏里看到的那张卡写；「还剩多久」每分钟都变，不算变了。"""
    import copy
    state = copy.deepcopy(HOME)
    state["sims"][1]["buffs"] = [
        {"t": "泡泡浴的余韵", "mood": "Happy", "w": 2, "from": "泡泡浴", "left": 200},
        {"t": "暴风雨", "mood": "Scared", "w": 1, "left": 45},
        {"t": "我喜欢聊天"},
        "old_style_name",
    ]
    state["sims"][1]["motives"] = {"Hygiene": -40, "TURBODRIVER:WickedWhims_Sex_Motive_Satisfaction": -100}
    core.record(tmp_path, core.clean_sync({"state": state, "screen": "live"}), now=1000)
    text = core.format_now(tmp_path, now=1001)
    assert "状态：泡泡浴的余韵（开心 +2｜来自 泡泡浴｜还剩 3 小时 20 分）、暴风雨（害怕 +1｜还剩 45 分钟）、我喜欢聊天、old_style_name" in text
    assert "告急 卫生 -40" in text and "WickedWhims" not in text
    core.note_for_him(tmp_path, now=1002)
    later = copy.deepcopy(state)
    later["sims"][1]["buffs"][0]["left"] = 190
    later["sims"][1]["buffs"][1]["left"] = 35
    core.record(tmp_path, core.clean_sync({"state": later}), now=1010)
    assert "跟上一句时一样" in core.note_for_him(tmp_path, now=1011)
    assert core.clean_command({"op": "moodlets", "args": {"who": "小椴"}}) == {"op": "moodlets", "args": {"who": "小椴"}}

    # 真机上来处那句本身带着「（来自……）」：不叠两遍
    assert core._buff_text({"t": "奢华保护", "mood": "Confident", "w": 1, "from": "（来自高品质的卫生棉条/卫生棉）"}) \
        == "奢华保护（自信 +1｜来自 高品质的卫生棉条/卫生棉）"

    # 她的小人换了件事做，状态没变：接着说的那句只带她在干嘛那一行，不重念一长串状态
    moved = copy.deepcopy(later)
    moved["sims"][1]["doing"] = [{"name": "bed_Sleep", "cn": "睡觉"}]
    core.record(tmp_path, core.clean_sync({"state": moved}), now=1020)
    delta = core.note_for_him(tmp_path, now=1021)
    assert "在 睡觉" in delta and "泡泡浴的余韵" not in delta
    # 反过来：多了一个状态，只带状态那一行
    moody = copy.deepcopy(moved)
    moody["sims"][1]["buffs"].append({"t": "睡得香", "mood": "Happy", "w": 1})
    core.record(tmp_path, core.clean_sync({"state": moody}), now=1030)
    delta = core.note_for_him(tmp_path, now=1031)
    assert "睡得香（开心 +1）" in delta and "在 睡觉" not in delta


def test_photo_is_shrunk_and_only_two_senders():
    import io

    from PIL import Image

    big = io.BytesIO()
    Image.new("RGB", (2560, 1440), (200, 120, 90)).save(big, format="PNG")
    assert core.clean_photo_query("her", " 自拍 ", "", "1") == {"by": "her", "caption": "自拍", "shot": 0, "hold": True}
    small = Image.open(io.BytesIO(core.shrink_photo(big.getvalue())))
    assert small.size == (1600, 900)
    for bad in ("everyone", "me", ""):
        with pytest.raises(ValueError):
            core.clean_photo_query(bad, "", "", "")
    with pytest.raises(ValueError):
        core.shrink_photo(b"not a picture")


def test_his_chat_reply_is_mirrored_into_the_game(tmp_path):
    """她开着游戏时 AI 在聊天里回的话，照样弹进游戏；游戏没开、她不在游戏世界里、他刚说过同一句，都不弹。"""
    assert core.mirror_pieces(tmp_path, "在吗", now=1000) == []                      # 游戏从没连过
    core.record(tmp_path, core.clean_sync({"state": HOME, "screen": "live"}), now=1000)
    assert core.mirror_pieces(tmp_path, "去洗澡。", now=1005) == ["去洗澡。"]
    assert core.mirror_pieces(tmp_path, "  ", now=1005) == []
    assert core.mirror_pieces(tmp_path, "去洗澡。", now=1000 + core.LIVE_SECONDS + 5) == []   # 游戏关了

    # 记一笔「他说过」不能把关了的游戏记成还开着
    core.log_events(tmp_path, [{"t": "he", "text": "去洗澡。"}], now=1006)
    assert core.last_seen(tmp_path) == 1000
    assert core.mirror_pieces(tmp_path, "去洗澡。", now=1007) == []                   # 刚在游戏里说过同一句
    assert core.mirror_pieces(tmp_path, "去洗澡。 ", now=1007 + core.MIRROR_SAME + 1) == []   # 游戏没再敲门：算关了
    core.record(tmp_path, core.clean_sync({"screen": "live"}), now=1200)
    assert core.mirror_pieces(tmp_path, "去洗澡。", now=1201) == ["去洗澡。"]          # 隔久了再说同一句：弹

    # 太长的按段拆，最多三条，再多的留在聊天里
    long = "\n".join(f"第{n}段" + "啊" * 200 for n in range(1, 7))
    pieces = core.mirror_pieces(tmp_path, long, now=1202)
    assert len(pieces) == 3 and pieces[0].startswith("第1段") and pieces[-1] == "（后面还有，在聊天里）"
    assert all(len(p) <= core.MIRROR_MAX for p in pieces)
    assert len(core.mirror_pieces(tmp_path, "哈" * 900, now=1203)[0]) == core.MIRROR_MAX

    # 她在捏人 / 读盘：通知弹不出来，不弹
    core.record(tmp_path, core.clean_sync({"screen": "cas"}), now=1210)
    assert core.mirror_pieces(tmp_path, "你在捏谁", now=1211) == []


def test_marks_in_his_reply_become_game_commands():
    """⟪小人:…⟫ 记号：说话的同时小人就去做，记号从她看到的正文里摘掉。"""
    text, marks = core.take_marks("过来。⟪小人:亲吻 → 小椴⟫\n\n抱一下。**⟪小人:紧紧拥抱->小椴⟫**")
    assert text == "过来。\n\n抱一下。"
    assert marks == [
        {"op": "do", "args": {"name": "亲吻", "target": "小椴"}, "label": "亲吻 → 小椴"},
        {"op": "do", "args": {"name": "紧紧拥抱", "target": "小椴"}, "label": "紧紧拥抱 → 小椴"},
    ]
    # 不写目标 = 对自己；动作名里可以有空格；别的括号写法也认
    assert core.take_marks("《小人：Shower With → showerBox》")[1] == [
        {"op": "do", "args": {"name": "Shower With", "target": "showerBox"}, "label": "Shower With → showerBox"}]
    assert core.take_marks("【小人:小睡一下】")[1] == [{"op": "do", "args": {"name": "小睡一下"}, "label": "小睡一下"}]
    # 换衣服、取消
    text, marks = core.take_marks("我去换一下。⟪小人:穿 睡衣⟫⟪小人:换上正装 2⟫⟪小人:取消⟫")
    assert text == "我去换一下。"
    assert [m["op"] for m in marks] == ["outfit", "outfit", "cancel"]
    assert marks[0]["args"] == {"name": "睡衣"} and marks[1]["args"] == {"name": "正装 2"}
    # 整条只有记号：正文是空的（不给她一个空泡）
    assert core.take_marks("⟪小人:亲吻 → 小椴⟫") == ("", [{"op": "do", "args": {"name": "亲吻", "target": "小椴"}, "label": "亲吻 → 小椴"}])
    # 没有记号的话原样不动；提到「小人」两个字不算记号
    plain = "你的小人自己跑去亲我了。\n\n  缩进也留着"
    assert core.take_marks(plain) == (plain, [])
    # 最多认六个
    assert len(core.take_marks("⟪小人:坐下⟫" * 9)[1]) == core.MARKS_MAX
    # 每条指令都过得了指令的校验
    for mark in core.take_marks("⟪小人:亲吻 → 小椴⟫⟪小人:穿 睡衣⟫⟪小人:取消⟫")[1]:
        assert core.clean_command({"op": mark["op"], "args": mark["args"]})["op"] == mark["op"]
    # 游戏回的话写进「最近」；中文名头一回用要再试一次
    assert core.format_event({"t": "did", "ok": True, "label": "亲吻 → 小椴", "text": "阿澈 排上了：亲吻"}) \
        == "你用记号排的「亲吻 → 小椴」：阿澈 排上了：亲吻"
    assert core.format_event({"t": "did", "ok": False, "label": "飞"}) == "你用记号排的「飞」：没排上"
    assert core.mark_needs_retry({"ok": False, "text": "「亲吻」这个名字刚去查了，过两三秒再 do 一次就认得了（或者先 list）。"})
    assert not core.mark_needs_retry({"ok": False, "text": "这里没有叫「飞」的动作。"})
    assert not core.mark_needs_retry({"ok": True, "text": "排上了"})


# ───────────────────────── 分享版多出来的 ─────────────────────────

def test_without_reply_wiring_the_hints_point_at_the_tool(tmp_path):
    """没把回话接进 /sims/reply 的接法（比如只加了 MCP 连接器）：提示语要让 AI 用 say，不能说「会自动弹」。"""
    core.SETTINGS.mirror = False
    note = core.tell_him_note("〔Sims 4 · 连着，她正在玩〕")
    assert "action=say" in note and "自动弹" not in note and "⟪小人" not in note
    core.record(tmp_path, core.clean_sync({"state": STATE, "screen": "live"}), now=1000)
    assert "action=say" in core.playing_hint(tmp_path, now=1005)
    core.note_for_him(tmp_path, now=1001)
    assert "action=say" in core.note_for_him(tmp_path, now=1002)       # 接着说的那句短提示也一样


def test_pronoun_can_be_changed_without_touching_what_she_typed(tmp_path):
    core.SETTINGS.pronoun = "他"
    core.record(tmp_path, core.clean_sync({"state": STATE, "screen": "live",
                                           "events": [{"t": "say", "text": "我跟她说过了"}]}), now=1000)
    text = core.voice(core.format_now(tmp_path, now=1001))
    assert "他正在玩" in text and "（他正点着的）" in text
    assert "他在游戏里说：「我跟她说过了」" in text                    # 玩家自己打的「她」原样留着
    assert "\ue000" not in text
    core.SETTINGS.pronoun = "她"
    assert core.voice("她在捏人界面") == "她在捏人界面"


def test_unseen_head_counts_what_she_said_since_the_last_look(tmp_path):
    core.record(tmp_path, core.clean_sync({"state": STATE, "events": [{"t": "say", "text": "在吗"}]}), now=1000)
    core.record(tmp_path, core.clean_sync({"events": [{"t": "say", "text": "看我新捏的裙子"}]}), now=1010)
    head = core.unseen_head(tmp_path, now=1020)
    assert "2 句" in head and "「在吗」" in head and "「看我新捏的裙子」" in head
    assert core.unseen_head(tmp_path, now=1030) == ""                   # 看过就不再提
    core.record(tmp_path, core.clean_sync({"events": [{"t": "say", "text": "人呢"}]}), now=1040)
    assert "1 句" in core.unseen_head(tmp_path, now=1050)


def test_photo_text_carries_her_caption():
    text = core.photo_text(2, "新家", "〔Sims 4 · 连着，她正在玩〕")
    assert "2 张截图" in text and "「新家」" in text and "连着" in text
    assert "附了一句" not in core.photo_text(1, "", "x")


def test_connected_but_not_in_a_save_yet(tmp_path):
    """真游戏里见到的：mod 在主菜单就开始敲门了，这时候还没有状态，不能说「还没连上过」。"""
    core.record(tmp_path, core.clean_sync({}), now=1000)
    assert "还没进到存档里" in core.format_now(tmp_path, now=1005)
    assert "还没连上过" in core.format_now(tmp_path, now=1000 + core.LIVE_SECONDS + 5)
    assert core.MOODS["Stressed"] == "压力大"
