# BufferIO

将 **vb（顶点缓冲）、ib（索引缓冲）等渲染资源缓冲导入 Blender** 的插件，主要面向基于 **3dmigoto / WWMI** 的 FrameAnalysis 转储资源（`.buf`、`.txt`、`.fmt` 文件）。

入口只有 **节点编辑器**：在 BufferIO 节点树侧栏选择 FMT 文件，插件自动把节点生成到一个节点框（NodeFrame）里，最后在 Import 节点上点按钮烘焙出网格与骨架。

- 版本：1.4.0
- 兼容 Blender：5.2（仅针对 5.2 API，不再兼容 4.x）
- 依赖：`numpy`（Blender 自带）
- 入口位置：节点编辑器 > 侧栏（N 键）> BufferIO

## 功能特性

- **从 FMT 生成节点**：选择 `.fmt`（WWMI 风格）或 3dmigoto FrameAnalysis 的 `txt`，自动解析布局、搜索同前缀的 ib/vb 资源，直接生成 `Vertex Buffer` / `Index Buffer` / `Mesh Assemble` / `Import` 节点并连好线。
- **节点框组织**：每次导入的节点都挂在同一个 `NodeFrame`（框）下，框名即 FMT 文件名，拖动框即整体移动。
- **完整属性支持**：位置、法线、切线、多套 UV（`TEXCOORD0-3`）、顶点色、骨骼权重（顶点组）、形态键（Shape Keys）。
- **骨骼矩阵与自动骨架**：导入 `BONEMATRIX`（`MATRIX3X4_FLOAT` 3×4 蒙皮矩阵）后，自动创建 Armature——所有骨骼 rest 位于原点（无父子），姿态直接应用骨骼矩阵，结合顶点组权重即可正确蒙皮。
- **形态键导入**：支持两种形态键数据来源（按偏移边界分组的 `SHAPEKEY_OFFSET/ID/OFFSET` 与逐顶点位移 `SHAPEKEY`），导入后命名为 `Deform N` 且数值归零，显示基础网格。
- **资源自动发现**：根据文件名前缀自动匹配同一资源组的 ib/vb 文件，支持 WWMI 与 FrameAnalysis 两种命名风格。
- **变换选项**：翻转环绕方向、翻转 UV 的 V 轴、全局缩放、X 轴镜像、坐标轴映射（统一转换到 Blender 的 -Y 前 / Z 上），全部在 `Import` 节点上。
- **顶点压缩**：自动去除未被索引引用的顶点，并重排索引与形态键顶点 id，缩小网格体积。

## 安装

1. 将 `BufferIO` 文件夹放入 Blender 的插件目录（或直接选择整个文件夹打包为 zip 后通过“安装插件”导入）。
2. 在 **偏好设置 > 插件** 中勾选 **BufferIO**。
3. 把任意编辑器的区域类型切换为 **节点编辑器**，或新建一个节点编辑器区域。

## 使用方法

### 1. 新建 / 打开节点树

在节点编辑器按 `N` 打开 **BufferIO** 侧栏：

- 如果当前不是在编辑 BufferIO 节点树，侧栏显示 **新建节点树** / **打开场景节点树**。
- 新建后节点编辑器会自动切换到该树，并记录在场景上（`Scene.bufferio_node_tree`），下次可一键打开。

### 2. 从 FMT 导入

点击侧栏的 **Import from FMT**，选择 `.fmt`（WWMI 风格）或 3dmigoto FrameAnalysis 的 `txt` / `buf` 文件。插件自动：

- 解析文件头部的 stride / element 布局；
- 搜索同前缀的 `.ib` / `.vb`（或 `.buf`）资源；
- 在光标位置生成一个节点框，框内创建：
  - 一个 `Index Buffer` 节点（含 ib txt 时自动解析 `first index` / `index count` / `byte offset`）；
  - 每个顶点元素一个 `Vertex Buffer` 节点，节点标签为 **`<Semantic Name> <Semantic Index>`**（如 `POSITION 0`、`TEXCOORD 1`）；
  - 一个 `Mesh Assemble` 节点（按元素数量自动增减 `ELEMENT[i]` 端口）与一个 `Import` 节点，并自动连好线。

无法自动识别的元素会保留为**静音（mute）节点**，标签使用原始语义名（如 `ATTRIBUTE 3`）：手动改语义后取消静音并连到 `Mesh Assemble` 的 `ELEMENT[i]` 端口即可。

可选参数（文件选择对话框右侧，整合为一个预设）：

- **Preset**：`Auto` / `WuWa`。选 `WuWa` 时会自动套用下面的搜索项与默认值，并把 FrameAnalysis 的 `ATTRIBUTE n` 映射为 `POSITION` / `TANGENT` / `NORMAL` / `TEXCOORD 0-3` / `COLOR` / 两组骨骼权重；映射结果直接显示在生成的 `Vertex Buffer` 节点标签上，并可在节点上逐项修改语义与索引。
- **Search Shape Keys**（勾选框）：WuWa 预设默认勾选；按同前缀 vb6 的 hash 定位形态键 CS draw call，创建一个多槽位的 `ShapeKey Assemble` 节点并自动接线。
- **Bone Matrix Tag**：WuWa 预设默认 `vs-cb4`；自动查找同 draw call 的矩阵文件并接到 `Import` 的 `Matrix` 输入。

`Import` 节点的默认值：Forward `Y`、Up `Z`、Scale `0.01`，Mirror X / Flip Winding / Flip UV 全部开启。

### 3. 烘焙

选中 `Import` 节点，点节点上的 **Import** 按钮（或侧栏/节点自带按钮）：

- 只接 `Mesh` → 生成网格对象；
- 只接 `Matrix` → 只生成骨架；
- 两者都接 → 生成带 Armature 修改器与父子关系的蒙皮网格。

求值失败时错误文本会写在对应节点上，同时以报告形式输出。

## 节点

在 BufferIO 节点树中按 `Shift+A` 可添加：

| 节点 | 说明 |
| --- | --- |
| `Index Buffer` | 读取索引缓冲（文件或 3dmigoto ib txt），输出索引；格式限定 `R16_UINT` / `R32_UINT` |
| `Vertex Buffer` | 读取任意顶点缓冲并标注语义，节点标签显示 `<Semantic Name> <Semantic Index>` |
| `Bone Matrix` | 读取骨骼蒙皮矩阵 |
| `ShapeKey Resource` | 读取一组分段形态键数据 |
| `ShapeKey Assemble` | 按槽位（`SHAPEKEY[i]`，用节点上的 +/− 增减）把多组形态键追加到网格（`Mesh` → `Mesh`） |
| `Mesh Assemble` | 装配索引与全部顶点属性，输出 `Mesh` |
| `Import` | 烘焙出网格 / 骨架；缩放、镜像、轴转换、翻转均在此节点 |
| `Format` / `String` / `Float` / `Int` / `Bool` | 值节点，输出常量供其它节点的输入端口使用 |

各节点的参数都有对应的输入端口（文件、格式、步长、偏移、数量等）：端口已连接时优先使用上游值，未连接时直接在端口上编辑（节点上不再重复一套控件）。`Index Buffer` 的 ib txt 只作为属性自动解析入口，不设输入；解析成功后会自动断开「格式 / 偏移 / 起始索引 / 索引数量」的输入连线，让解析结果生效。

`Vertex Buffer` 在语义为 `NORMAL` 时额外提供 **算法** 选项：`保持`（默认，按格式规范解码）与 `终末地`（八面体法线解码，选中时自动把格式切换为 `R10G10B10A2_UNORM` 并断开格式输入连线）。

## 支持的语义

| 语义 | 说明 |
| --- | --- |
| `INDEX` | 三角形索引缓冲（支持直接解析 3dmigoto ib txt） |
| `POSITION` | 顶点位置（必需） |
| `NORMAL` | 顶点法线 |
| `TANGENT` | 顶点切线（导入到 `TANGENT` 自定义属性，Blender 无原生切线存储） |
| `COLOR` | 顶点色 |
| `TEXCOORD` | UV 贴图坐标（支持 0-3 多套） |
| `BLENDINDICES` | 骨骼权重索引（生成顶点组） |
| `BLENDWEIGHTS` | 骨骼权重值 |
| `SHAPEKEY_OFFSET` | 形态键顶点偏移边界（`R32_UINT`，如 `[0,1244,...]`） |
| `SHAPEKEY_VERTEXID` | 形态键顶点 id 列表（`R32_UINT`） |
| `SHAPEKEY_VERTEXOFFSET` | 形态键顶点位移向量列表（`R16G16B16_FLOAT`） |
| `SHAPEKEY` | 形态键逐顶点位移（索引即 Deform 编号，如 `SHAPEKEY 23` = `Deform 23`） |
| `BONEMATRIX` | 骨骼 3×4 矩阵（`MATRIX3X4_FLOAT`，索引即骨骼号，与 `BLENDINDICES` 对应） |
| `SKIP` | 不导入该元素 |

`Vertex Buffer` 只处理逐顶点属性；索引走 `Index Buffer`，形态键分段数据走 `ShapeKey Resource`，骨骼矩阵走 `Bone Matrix`。

## 变换选项

均在 `Import` 节点上：

- **翻转环绕方向**：翻转三角形顶点顺序，影响面法线方向（默认开启）。
- **翻转 UV 的 V 轴**：`V = 1 - V`（默认开启）。
- **镜像（X 轴）**：沿 X 轴镜像网格，并同步翻转法线/切线 X 分量与环绕方向（默认开启）。
- **全局缩放**：顶点坐标缩放系数，如鸣潮（WuWa）游戏单位转米可用 `0.01`（默认）。
- **坐标轴（前 / 上）**：源资源的朝前轴与朝上轴，导入时统一映射到 Blender 的 -Y 前 / Z 上。

## 支持的 DXGI 格式

- 分量类型：`FLOAT`、`UINT`、`SINT`、`UNORM`、`SNORM`
- 位宽：8 / 16 / 32 位
- 通道：`R`、`RG`、`RGB`、`RGBA`，按 DXGI 命名解析顺序（`B8G8R8A8` 会重排为 RGBA，`X8` 占位通道丢弃）
- 打包 / 混合位宽：`R10G10B10A2_UNORM` / `R10G10B10A2_UINT`、`B5G6R5_UNORM`、`B5G5R5A1_UNORM`、`B4G4R4A4_UNORM`、`R11G11B10_FLOAT`、`R9G9B9E5_SHAREDEXP`
- sRGB：`R8G8B8A8_UNORM_SRGB` / `B8G8R8A8_UNORM_SRGB` 会按 sRGB EOTF 转线性
- `_TYPELESS`：按位宽推断（32 位当浮点、8/16 位当 UNORM）
- 扩展：`MATRIX3X4_FLOAT`（骨骼 3×4 矩阵，48 字节）、24 位 `R16G16B16_FLOAT` 等 3dmigoto 社区格式
- `UNORM` / `SNORM` 在导入时会自动归一化到 `[0,1]` / `[-1,1]`（`SNORM` 按规范截断）

## 资源命名约定

插件按文件名前缀自动匹配同一资源组：

- **WWMI（.fmt）**：`Component 0.fmt` → `Component 0.ib` / `Component 0.vb`
- **FrameAnalysis（txt）**：`000984-vb0=hash-vs=...-ps=....txt` → 同前缀 `000984-ib=*.txt/.buf`、`000984-vb*=*.buf`

## 与原 3D 视图侧栏的差异

插件不再提供 3D 视图侧边栏，原面板功能在节点侧的对应：

| 原面板功能 | 节点侧现状 |
| --- | --- |
| 加载 FMT、逐元素生成 | 侧栏 **Import from FMT**，一次性生成节点框 |
| 元素列表逐项编辑（语义 / 格式 / 步长 / 偏移 / 文件） | 每个 `Vertex Buffer` 节点即一个元素，参数在端口上编辑 |
| 手动添加元素 | `Shift+A` 添加 `Vertex Buffer` 节点后手动填参数 |
| 布局校验（红/黄高亮、校验全部、缺失必需语义提示） | **未保留**（求值时对缺少 POSITION / 索引等会直接报错，但不再有逐项可视化校验） |
| 语义方案（JSON 预设） | 改为 **Blender 原生操作项预设**（`Import from FMT` 文件对话框右侧的下拉菜单，可添加 / 移除自定义预设）；语义映射表（`(Semantic Name, Semantic Index) -> (Semantic, Target Index)`）以 `Semantic Mapping` 属性列表直接显示并可逐条调整，形态键搜索 / 骨骼矩阵 tag 也可在右侧直接修改 |
| 批量目录导入（一次导入多组 draw call） | **未保留**（一次导入一个 FMT；可重复导入到同一棵树，每组一个节点框） |
| 按 .buf 文件名自动推导对象名 | 仍用于 `Bone Matrix` 节点命名；网格对象名在 `Import` 节点上手动设置 |

语义映射以操作符属性形式暴露（`operators.py` 的 `BUFFERIO_AttributeItem`），预设即操作符属性快照。操作符 `bl_options` 含 `'PRESET'`，Blender 会在文件对话框右侧自动绘制原生"Operator Presets"行（`WM_MT_operator_presets` 下拉 + 添加/移除），预设保存在 Blender 用户目录 `presets/operator/bufferio.node_import_fmt/`；内置 WuWa 预设随插件分发在 `presets/operator/bufferio.node_import_fmt/WuWa.py`（由 `__init__.py` 注册预设路径后出现在菜单中）。

## 目录结构

```
BufferIO/
├── __init__.py      # 插件入口：Scene 属性定义、模块注册
├── constants.py     # 语义枚举、坐标轴
├── properties.py    # FMT 解析为轻量元素对象（导入时一次性使用）
├── core.py          # 索引读取、形态键截断、网格构建与链接
├── operators.py     # 从 FMT 生成节点（节点框内自动装配）
├── buffer_io.py     # 缓冲读取、网格 / 骨架对象构建
├── storage.py       # 底层二进制读取（mmap 缓存）、索引解析与顶点压缩
├── dxgi.py          # DXGI 格式定义
├── fmt_parser.py    # fmt / 3dmigoto txt 解析与资源发现
└── nodes/           # 节点系统
    ├── tree.py              # BufferIO 节点树
    ├── sockets.py           # 自定义 Socket
    ├── base.py              # 节点基类
    ├── evaluator.py         # 拉取式求值器
    ├── element_semantic.py  # Vertex Buffer 节点
    ├── index_buffer.py      # Index Buffer 节点
    ├── bone_matrix.py       # Bone Matrix 节点
    ├── shape_key.py         # ShapeKey Resource 节点
    ├── shape_key_apply.py   # ShapeKey Assemble 节点
    ├── assemble.py          # Mesh Assemble 节点
    ├── output.py            # Import 节点
    ├── value.py             # 值节点
    └── ui.py                # 侧栏面板、操作符、Shift+A 菜单
```

## 说明

- 形态键数据在导入时会做截断处理：若 `ShapeKeyOffset` 出现不递增（数据末尾存在无效数据），其后的全部数据会被舍弃。
- 切线保存为网格的自定义属性 `TANGENT`（`FLOAT_VECTOR`，逐顶点），而非原生切线层。
