# World Relay（存档中继站）

当前版本：**v0.10.0 Beta 1**（内部版本号：`0.10.0-beta.1`）

World Relay 是一个 Windows 桌面版 Minecraft 联机存档管理工具。程序使用
PyWebView 显示独立桌面窗口，不需要用户在浏览器中访问地址；所有页面和接口都只在
本机 `127.0.0.1` 上运行，存档不会上传到网络。

> Beta 提示：首次正式发布前请先使用不重要的存档验证，并保留自己的额外备份。

## 普通用户如何使用

1. 打开发布文件夹 `WorldRelay-v0.10.0-beta.1`。
2. 双击 `WorldRelay.exe`，不要单独移动这个 EXE，也不要删除旁边的 `_internal` 文件夹。
3. 第一次启动后进入“存档管理”。
4. 选择 Minecraft 的 `.minecraft` 文件夹，再选择用于管理新联机存档的 `saves` 文件夹。
5. 保存路径；在存档列表中给存档指定对应的 Minecraft 版本。
6. 在“可选服主管理”中为玩家执行正版验证，并加入该存档的服主白名单。
7. 回到主页，依次选择版本、存档、新服主，确认后点击“开始替换”。
8. 等待进度弹窗显示成功或失败，再点击“确定”。

加入白名单时需要连接 Mojang 正版档案服务。网络暂时不可用时，软件会提示稍后重试，
不会把连接失败误判为离线 UUID。玩家改名后 UUID 白名单仍然有效，界面会以正版服务
返回的当前名称显示。

配置文件保存在：

```text
%APPDATA%\WorldRelay\world_relay_config.json
```

运行日志保存在：

```text
%APPDATA%\WorldRelay\logs\world-relay.log
```

如果该目录不可写，启动日志会回退到系统临时目录下的 `WorldRelay\logs`。

软件运行依赖 Microsoft Edge WebView2 Runtime。Windows 10/11 与新版 Microsoft Edge
通常已包含它；如果窗口无法正常显示，可安装或修复 WebView2 Runtime 后重试。

## 功能说明

- 从 `.minecraft/versions` 读取可用版本。
- 从指定的 `saves` 目录读取、添加和删除联机存档。
- 根据存档玩家 DAT 文件与对应版本的 `usercache.json` 显示“玩家名：玩家 UID”。
- 每个存档维护独立的服主白名单；白名单以 UUID 为准，玩家名称只用于显示。
- 通过 Mojang 正版档案服务确认 UUID 后，才允许将玩家加入服主白名单。
- 同名的正版与离线 UUID 会分开显示，主页只列出当前存档中已加入白名单的 UUID。
- 修改来源存档 `level.dat` 中的 `Data/singleplayer_uuid`。
- 把修改后的完整存档安全替换到 `.minecraft/versions/<版本>/saves/<存档>`。
- 修改 `level.dat` 前创建 `level.dat.owner-change.bak` 备份。

写入范围仅包括用户指定的 `saves` 目录、目标版本的 `saves` 子目录，以及用户配置目录。
`.minecraft` 的其他内容和 `usercache.json` 只读。服主白名单保存在软件配置文件中，
不会写回 Minecraft 缓存。项目根目录原有的 `Replacer.py` 不会被修改或调用。

白名单与当前 `saves` 根目录绑定。切换到另一个 `saves` 根目录、删除存档，或导入并
替换同名存档时，对应白名单会被清空，避免把旧世界的授权错误带入新世界。

## 软件根目录文件说明

| 文件或目录 | 作用 |
| --- | --- |
| `README.md` | 当前说明文档；包含软件用法、文件职责、构建方法和版本信息。 |
| `LICENSE` | MIT 开源许可证；发布包中也会保留该文件。 |
| `desktop.py` | 桌面版入口；创建 PyWebView 窗口、启动/停止本地服务并记录启动错误。 |
| `app.py` | 本地 HTTP 接口、静态页面服务、后台任务和文件夹选择器。 |
| `core.py` | 存档扫描、玩家映射、NBT 修改、安全复制、导入和删除等核心逻辑。 |
| `app_info.py` | 软件名称与 Beta 版本号的唯一代码定义。 |
| `assets/` | 软件品牌图标源文件及用于 EXE 的多尺寸 Windows 图标。 |
| `tools/generate_icon.py` | 根据界面左上角品牌标志重新生成 Windows ICO。 |
| `static/` | 桌面窗口中显示的 HTML、CSS 和 JavaScript 界面。 |
| `tests/` | 核心逻辑及本地接口的自动化测试。 |
| `world_relay.spec` | PyInstaller 文件夹版打包配置。 |
| `world_relay_version.txt` | 写入 `WorldRelay.exe` 属性页的 Windows 版本信息。 |
| `requirements.txt` | 桌面版运行依赖。 |
| `requirements-dev.txt` | 测试、打包和图标生成所需的开发依赖。 |
| `build_folder.bat` | 优先使用项目 `.venv`，也可通过系统 Python 3.11 重新构建文件夹版。 |
| `启动存档中继站.bat` | 开发辅助启动器；优先启动最新的已构建 EXE，否则使用项目虚拟环境或系统 Python 3.11。 |
| `build/` | PyInstaller 的中间构建文件，可重新生成，不需要分发。 |
| `dist/WorldRelay-v0.10.0-beta.1/` | 最终文件夹版发布目录，需要整体复制给用户。 |

## 开发者重新构建

构建环境为 Windows，推荐使用 Python 3.11 和项目虚拟环境：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

双击 `build_folder.bat`，或在本目录运行：

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean world_relay.spec
```

本项目采用 PyInstaller **文件夹版（onedir）**，产物位于
`dist\WorldRelay-v0.10.0-beta.1`。分发时必须复制整个文件夹，而不是只发送 EXE。

## 源码测试

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

## GitHub 发布

仓库中的测试工作流会在推送和拉取请求时使用 Windows 与 Python 3.11 运行测试。
发布时先更新 `app_info.py` 中的版本号，再创建完全匹配的标签，例如
`v0.10.0-beta.1`。标签推送后，发布工作流会测试、构建、压缩文件夹版，生成
SHA-256 校验文件，并创建 GitHub Release。`build/` 与 `dist/` 都是本地生成物，
不应提交到 Git。

## 许可证

本项目采用 [MIT License](LICENSE) 开源。你可以使用、复制、修改和分发本软件，
但必须在副本或主要部分中保留原版权声明与许可证声明。本软件按“原样”提供，
不附带任何明示或暗示的担保；操作 Minecraft 存档前仍应自行保留额外备份。
