import re

from pathlib import Path


class FmtError(ValueError):
    pass


class FmtElement:
    def __init__(self, semantic_name, semantic_index, format, input_slot, byte_offset, input_slot_class='per-vertex'):
        self.semantic_name = semantic_name
        self.semantic_index = semantic_index
        self.format = format
        self.input_slot = input_slot
        self.byte_offset = byte_offset
        self.input_slot_class = input_slot_class

    @property
    def is_per_vertex(self) -> bool:
        return self.input_slot_class == 'per-vertex'

    def __repr__(self):
        return f'FmtElement({self.semantic_name}{self.semantic_index} {self.format} slot={self.input_slot} offset={self.byte_offset})'


class FmtData:
    """3dmigoto fmt / txt 头部信息"""
    def __init__(self):
        self.stride = 0
        self.topology = 'trianglelist'
        # IB 信息
        self.ib_format = ''
        self.byte_offset = 0
        self.first_index = 0
        self.index_count = 0
        # VB 信息
        self.first_vertex = 0
        self.vertex_count = 0
        # 元素
        self.elements = []


def parse_fmt_text(text: str) -> FmtData:
    """解析 WWMI .fmt 或 3dmigoto FrameAnalysis .txt 的头部"""
    fmt = FmtData()
    current_element = None
    elements = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(('vertex-data', 'instance-data')):
            break
        if line.startswith('element['):
            end = line.find(']')
            if end == -1:
                raise FmtError(f'元素行损坏: `{line}`')
            element_id = int(line[len('element['):end])
            current_element = {}
            elements[element_id] = current_element
            continue
        if ':' not in line:
            # 进入数据区（如 ib txt 的索引列表）
            break

        key, _, value = line.partition(':')
        key = key.strip()
        value = value.strip()

        if current_element is not None:
            current_element[key] = value
            continue

        if key == 'stride':
            fmt.stride = int(value)
        elif key == 'topology':
            fmt.topology = value
        elif key == 'format':
            fmt.ib_format = value.replace('DXGI_FORMAT_', '')
        elif key == 'byte offset':
            fmt.byte_offset = int(value)
        elif key == 'first index':
            fmt.first_index = int(value)
        elif key == 'index count':
            fmt.index_count = int(value)
        elif key == 'first vertex':
            fmt.first_vertex = int(value)
        elif key == 'vertex count':
            fmt.vertex_count = int(value)

    for element_id in sorted(elements.keys()):
        e = elements[element_id]
        try:
            fmt.elements.append(FmtElement(
                semantic_name=e['SemanticName'].upper(),
                semantic_index=int(e['SemanticIndex']),
                format=e['Format'].replace('DXGI_FORMAT_', ''),
                input_slot=int(e['InputSlot']),
                byte_offset=int(e['AlignedByteOffset']),
                input_slot_class=e.get('InputSlotClass', 'per-vertex'),
            ))
        except KeyError as err:
            raise FmtError(f'element[{element_id}] 缺少字段 {err}')

    if fmt.topology != 'trianglelist':
        raise FmtError(f'暂不支持拓扑类型: {fmt.topology}')

    return fmt


def parse_fmt_file(path: Path) -> FmtData:
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return parse_fmt_text(f.read())


class ResourceSet:
    """fmt 文件对应的 ib/vb 资源文件"""
    def __init__(self):
        self.kind = ''              # 'FMT'（WWMI）或 'FA'（FrameAnalysis）
        self.ib_txt = None          # FA 模式的 ib txt（含 format/first/count）
        self.ib_data = None         # ib 数据文件路径
        self.vb_files = {}          # input_slot -> vb 数据文件路径
        self.vb_txt_files = {}      # input_slot -> vb 的 txt 头部文件路径（含 byte offset/stride）


def discover_resources(fmt_path: Path) -> ResourceSet:
    """根据 fmt 文件路径自动搜索同前缀的 ib/vb 资源"""
    resources = ResourceSet()
    fmt_path = Path(fmt_path)
    directory = fmt_path.parent

    if fmt_path.suffix.lower() == '.fmt':
        # WWMI 风格: Component 0.fmt -> Component 0.ib / Component 0.vb
        resources.kind = 'FMT'
        ib_path = fmt_path.with_suffix('.ib')
        vb_path = fmt_path.with_suffix('.vb')
        if not ib_path.is_file():
            raise FmtError(f'找不到索引缓冲文件: {ib_path}')
        if not vb_path.is_file():
            raise FmtError(f'找不到顶点缓冲文件: {vb_path}')
        resources.ib_data = ib_path
        resources.vb_files = {0: vb_path}
        return resources

    # FrameAnalysis 风格: 000984-vb0=hash-vs=...-ps=....txt
    match = re.match(r'^(\d+)-', fmt_path.name)
    if not match:
        raise FmtError(f'无法从文件名识别资源前缀: {fmt_path.name}')
    prefix = match.group(1)
    resources.kind = 'FA'

    # 搜索 ib: 000984-ib=....txt / .buf
    ib_txt_list = sorted(directory.glob(f'{prefix}-ib=*.txt'))
    if not ib_txt_list:
        raise FmtError(f'找不到索引缓冲: {prefix}-ib=*.txt')
    resources.ib_txt = ib_txt_list[0]
    ib_buf = resources.ib_txt.with_suffix('.buf')
    if not ib_buf.is_file():
        raise FmtError(f'找不到索引缓冲数据: {ib_buf}')
    resources.ib_data = ib_buf

    # 搜索 vb: 000984-vb0=...buf, 000984-vb1=...buf ...
    for vb_buf in sorted(directory.glob(f'{prefix}-vb*=*.*')):
        if vb_buf.suffix.lower() != '.buf':
            continue
        slot_match = re.match(rf'^{re.escape(prefix)}-vb(\d+)=', vb_buf.name)
        if slot_match:
            slot = int(slot_match.group(1))
            resources.vb_files[slot] = vb_buf
            # 同 basename 的 txt（含 byte offset/stride 等头部）
            vb_txt = vb_buf.with_suffix('.txt')
            if vb_txt.is_file():
                resources.vb_txt_files[slot] = vb_txt

    if not resources.vb_files:
        raise FmtError(f'找不到顶点缓冲: {prefix}-vb*=*.buf')

    return resources
