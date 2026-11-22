# Claude 桌面版扩展（不用服务器的装法）

这个文件夹是扩展包的壳：清单、依赖、入口。真正的代码是 `server/sulsul_server`，打包时拷进来。

```bash
./pack.sh        # 在仓库根目录；会生成 dist/sulsul-with-ta.mcpb
```

格式是 [MCPB](https://github.com/modelcontextprotocol/mcpb) 的 `uv` 类型：Python 和依赖由 Claude 桌面版自己装，用户不用装 Python。
