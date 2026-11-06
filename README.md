# BufferIO

将 **vb（顶点缓冲）、ib（索引缓冲）等渲染资源缓冲导入 Blender** 的插件，主要面向基于 **3dmigoto / WWMI** 的 FrameAnalysis 转储资源（`.buf`、`.txt`、`.fmt` 文件）。

插件通过解析资源布局（格式、步长、偏移、语义）重建网格，支持顶点法线/切线、多套 UV、顶点色、骨骼权重与形态键（Shape Keys）等完整属性导入。

- 版本：1.3.0
- 兼容 Blender：5.2+（仅针对 5.2 API，不再兼容 4.x）
- 依赖：`numpy`（Blender 自带）
- 面板位置：3D 视图 > 侧边栏 > BufferIO

## 功能特性

- **FMT 模式**：加载 `.fmt` / 3dmigoto `txt` 文件，自动解析布局并搜索同前缀的 ib/vb 资源，语义自动猜测、可手动修正；也可手动添加元素逐项指定文件、格式、步长、偏移后导入。
- **完整属性支持**：位置、法线、切线、多套 UV（`TEXCOORD0-3`）、顶点色、骨骼权重（顶点组）、形态键（Shape Keys）。
- **骨骼矩阵与自动骨架**：导入 `BONEMATRIX`（`MATRIX3X4_FLOAT` 3×4 蒙皮矩阵）后，自动创建 Armature——所有骨骼 rest 位于原点（无父子），姿态直接应用骨骼矩阵，结合顶点组权重即可正确蒙皮。
- **形态键导入**：支持两种形态键数据来源（按偏移边界分组的 `SHAPEKEY_OFFSET/ID/OFFSET` 与逐顶点位移 `SHAPEKEY`），导入后命名为 `Deform N` 且数值归零，显示基础网格。
- **资源自动发现**：根据文件名前缀自动匹配同一资源组的 ib/vb 文件，支持 WWMI 与 FrameAnalysis 两种命名风格。
- **布局校验**：自动检测步长不一致、格式越界、布局不连续、语义冲突等常见配置错误，并在列表中高亮提示。
- **语义方案 / 预设**：可把元素配置（语义映射、格式、步长、偏移）保存为 JSON 方案，随插件携带、随时复用。
- **变换选项**：翻转环绕方向、翻转 UV 的 V 轴、全局缩放、X 轴镜像、坐标轴映射（统一转换到 Blender 的 -Y 前 / Z 上）。
- **顶点压缩**：自动去除未被索引引用的顶点，并重排索引与形态键顶点 id，缩小网格体积。

## 安装

1. 将 `BufferIO` 文件夹放入 Blender 的插件目录（或直接选择整个文件夹打包为 zip 后通过“安装插件”导入）。
2. 在 **偏好设置 > 插件** 中勾选 **BufferIO**。
3. 打开 3D 视图，在 **侧边栏（N 键）> BufferIO** 面板中使用。

> 安装目录下会自动生成 `semantics/` 文件夹，用于存放保存的语义方案。

## 使用方法

### 使用方式

1. 点击 **加载 FMT**，选择 `.fmt`（WWMI 风格）或 3dmigoto FrameAnalysis 的 `txt` / `buf` 文件。插件自动：
   - 解析文件头部的 stride / element 布局；
   - 搜索同前缀的 `.ib` / `.vb`（或 `.buf`）资源；
   - 生成元素列表并自动猜测每个元素的语义（可在列表中手动调整，`SKIP` 表示不导入）。
2. 没有布局文件时，可点击 **添加元素** 手动新增条目，逐项设置语义、格式、步长、偏移、文件路径后导入。
3. 若元素已存在（手动添加或加载语义预设），可在文件选择对话框右侧勾选 **按tag填路径**：仅按文件名前缀自动填充元素路径，无需 txt 头部，可直接选择 `.buf`。
4. 点击 **导入** 生成网格。

> 索引缓冲（`IndexBuffer`）元素会自动置顶；选择 `txt` 路径后会自动解析其头部并填入 `first index` / `index count` / `byte offset`。

## 节点编辑器

节点编辑器新建 **BufferIO 节点树** 后，可通过 `Shift+A` 添加以下节点：

| 节点 | 说明 |
| --- | --- |
| `VB ELEMENT DESC` | 资源元素描述节点组：外部只有一个 `Mesh` 输出端口，内部由 `Vertex Buffer` / `IndexBuffer` 节点组成 |
| `Node Group` | 空节点组：先按 `Tab` 进入内部搭链，再在 `Group Interface` 里定义对外端口（`Ctrl+G` 编组也生成这种节点） |
| `IndexBuffer` | 读取索引缓冲（文件或 3dmigoto ib txt），输出索引 Socket；格式限定 `R16_UINT` / `R32_UINT` |
| `Vertex Buffer` | 读取任意顶点缓冲并标注语义（节点组的内部元素节点） |
| `Bone Matrix` / `ShapeKey` / `ShapeKey Assemble` / `Mesh Assemble` / `Import` | 装配链节点（缩放 / 镜像 / 轴转换 / 翻转已并入 `Import`，不再单独成节点） |
| `格式` / `字符串` / `浮点值` / `整数值` / `布尔值` | 值节点，输出常量供其它节点的输入端口使用 |

各节点的参数都有对应的输入端口（文件、格式、步长、偏移、数量等）：端口已连接时优先使用上游值，未连接时直接在端口上编辑（节点上不再重复一套控件）。`IndexBuffer` 的 ib txt 只作为属性自动解析入口，不设输入；解析成功后会自动断开「格式 / 偏移 / 起始索引 / 索引数量」的输入连线，让解析结果生效。

`Vertex Buffer` 在语义为 `NORMAL` 时额外提供 **算法** 选项：`保持`（默认，按格式规范解码）与 `终末地`（八面体法线解码，选中时自动把格式切换为 `R10G10B10A2_UNORM` 并断开格式输入连线）。

### 通用节点组（Ctrl+G）

框选若干节点后按 `Ctrl+G`，会把它们合并为一个 `节点组` 节点：节点与内部连线复制进新建的内部树，跨越选区的连线转成组的输入/输出端口，并按原位置自动重连。之后同样按 `Tab` 进入内部编辑，再按 `Tab` 返回上层。

- 节点上的 **Ungroup** 按钮（或 `Ctrl+Alt+G`）会把组节点还原成普通节点，内部连线与外部连线一并恢复。
- 节点上有 **Tree** 数据块选择器，可直接复用已有的 BufferIO 节点组树；切换后端口立即按新接口重建。
- 组节点名称跟随内部树名（在侧栏 **Group Name** 改名会同步到所有实例）；手动改过节点 label 后不再被覆盖。
- 端口实时同步：修改组内接口（增删 / 改名）后，外层组节点的端口会在约 0.6 秒内自动对齐，不必 Tab 进出（同一棵内部树的多个实例一起更新）。
- 进入内部后，侧边栏 **Group Interface** 区域可增删输入/输出端口、改名、写描述，并用 ↑/↓ 调整端口顺序；返回父级时组节点外部端口自动同步。
- 标量端口（Float / Int / Bool / String / Format）未连线时，组节点端口上直接出现可编辑控件（按实例保存）；填 0 / 空值视为未填写，仍由内部节点自身属性兜底。
- 组节点上显示内部节点数、输出数与最近一次错误；求值失败时错误文本直接留在节点上。
- 选中组节点时，侧边栏也会显示它的接口列表，可在组外增删/改名端口，改完点 **Sync Ports**（节点上也有同名按钮）立即刷新外部端口；同一棵内部树的多个实例会一起刷新。
- 空组节点第一次点 **Edit Interior** 时会自动补建内部树与 `Group Input` / `Group Output` 节点；组内自引用或 `A → B → A` 的循环编组在求值时会直接报错，不会卡死。

`VB ELEMENT DESC` 是一个**可进入内部的节点组**（行为与材质节点组一致）：

- 选中节点按 `Tab`（或节点上的 **编辑内部**）进入内部树；在内部再按 `Tab`（或侧边栏 **返回上层**）退出并同步外部元素列表。
- 内部是真正的节点组结构：`Group Input` / `Group Output` 节点 + 树接口，元素节点先汇入 `Mesh Assemble` 再接到唯一的 `Mesh` 输出端口（外部也就只有一个网格输出）。
- 外部列表、属性与输出端口都是内部节点的投影：在外部改属性会写入内部节点，在内部改节点后返回会重建外部列表与端口。
- **保存预设 / 加载预设** 直接作用于内部节点：加载预设会按新配置重建内部节点组（保留已有文件路径）。
- 解析 `.fmt` / `txt` 后会自动创建内部节点；旧版保存的节点在首次绘制或进入内部时自动补建。

## 支持的语义

| 语义 | 说明 |
| --- | --- |
| `IndexBuffer` | 三角形索引缓冲（支持直接解析 3dmigoto ib txt） |
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
| `SKIP` | 不导入该元素（仅 FMT 模式） |

其中 `IndexBuffer` 与 `POSITION` 为必需语义，缺失时导入会给出警告。

## 变换选项

- **翻转环绕方向**：翻转三角形顶点顺序，影响面法线方向（默认开启）。
- **翻转 UV 的 V 轴**：`V = 1 - V`（默认开启）。
- **镜像（X 轴）**：沿 X 轴镜像网格，并同步翻转法线/切线 X 分量与环绕方向。
- **全局缩放**：顶点坐标缩放系数，如鸣潮（WuWa）游戏单位转米可用 `0.01`（默认）。
- **坐标轴（前 / 上）**：源资源的朝前轴与朝上轴，导入时统一映射到 Blender 的 -Y 前 / Z 上。

## 布局校验规则

点击 **校验步长/偏移** 可手动触发校验，状态图标显示在列表项前：

- **红色（ERROR）**：同文件步长不一致；格式越界（偏移 + 字节宽度 > 步长）；语义冲突（同一原始语义被重复映射）。
- **黄色（QUESTION）**：相邻项偏移差 ≠ 前一项格式字节宽度（布局不连续）。
- 缺失必需语义（`IndexBuffer` / `POSITION`）时给出警告。

校验仅作提示，不影响导入。

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

## 目录结构

```
BufferIO/
├── __init__.py      # 插件入口：Scene 属性定义、模块注册
├── constants.py     # 语义枚举、坐标轴、目录、动态枚举辅助
├── properties.py    # PropertyGroup 数据模型与属性更新回调
├── core.py          # 校验、顶点数组收集、网格构建与链接
├── operators.py     # 全部操作符
├── ui.py            # UIList 与主面板
├── buffer_io.py     # 网格 / 骨架对象构建
├── storage.py       # 底层二进制读取（mmap 缓存）、索引解析与顶点压缩
├── dxgi.py          # DXGI 格式定义
├── fmt_parser.py    # fmt / 3dmigoto txt 解析与资源发现
├── nodes/           # 节点系统
│   ├── element_desc.py      # VB ELEMENT DESC 节点组（内部由元素节点组成）
│   ├── element_semantic.py  # Vertex Buffer 元素节点（原“通用缓冲 / Buffer Semantic”）
│   ├── index_buffer.py      # IndexBuffer 索引节点
│   └── ...                  # 装配 / 变换 / 输出 / 骨骼 / 形态键等
└── semantics/       # 语义映射方案（JSON，随插件保存）
    └── wuwa.json    # 鸣潮（WuWa）示例语义方案
```

## 附带示例

仓库自带基于 **鸣潮（WuWa）** 资源的示例配置：

- `semantics/wuwa.json`：FrameAnalysis 转储的 `ATTRIBUTE n` → 语义映射（如 `ATTRIBUTE 0` → `POSITION`）。

可在 **Load Semantics** 中直接加载使用，作为其他游戏的参考模板。

## 说明

- 形态键数据在导入时会做截断处理：若 `ShapeKeyOffset` 出现不递增（数据末尾存在无效数据），其后的全部数据会被舍弃。
- 切线保存为网格的自定义属性 `TANGENT`（`FLOAT_VECTOR`，逐顶点），而非原生切线层。
