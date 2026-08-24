# BufferIO

将 **vb（顶点缓冲）、ib（索引缓冲）等渲染资源缓冲导入 Blender** 的插件，主要面向基于 **3dmigoto / WWMI** 的 FrameAnalysis 转储资源（`.buf`、`.txt`、`.fmt` 文件）。

插件通过解析资源布局（格式、步长、偏移、语义）重建网格，支持顶点法线/切线、多套 UV、顶点色、骨骼权重与形态键（Shape Keys）等完整属性导入。

- 版本：1.0.0
- 兼容 Blender：4.0+
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
- **顶点压缩**：自动去除未被索引引用的顶点，缩小网格体积。

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

> 索引缓冲（`INDEX`）元素会自动置顶；选择 `txt` 路径后会自动解析其头部并填入 `first index` / `index count` / `byte offset`。

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
| `SKIP` | 不导入该元素（仅 FMT 模式） |

其中 `INDEX` 与 `POSITION` 为必需语义，缺失时导入会给出警告。

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
- 缺失必需语义（`INDEX` / `POSITION`）时给出警告。

校验仅作提示，不影响导入。

## 支持的 DXGI 格式

- 分量类型：`FLOAT`、`UINT`、`SINT`、`UNORM`、`SNORM`
- 位宽：8 / 16 / 32 位
- 通道：`R`、`RG`、`RGB`、`RGBA`
- 附加：`B8G8R8A8_UNORM`、`B8G8R8A8_SNORM`、`MATRIX3X4_FLOAT`（骨骼 3×4 矩阵，48 字节）
- `UNORM` / `SNORM` 在导入时会自动归一化到 `[0,1]` / `[-1,1]`

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
├── buffer_io.py     # 底层二进制读取与网格对象构建
├── dxgi.py          # DXGI 格式定义
├── fmt_parser.py    # fmt / 3dmigoto txt 解析与资源发现
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
