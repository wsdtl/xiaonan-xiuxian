"""正式 JSON 数据核心微服务。

除正式数据快照外，本包还公开字段契约（schema）的通用校验引擎：各领域服务
用它校验自己拥有的 JSON 是否符合已声明的字段契约，避免各自手写一遍类型与
引用检查。契约的书写约定见 `data/schema编写规范.md`。

`fields.py` 是同一职责的更小一层：取单个字段时确认形状（正整数 / 非负整数 /
对象 / 非空文本）。这四个判定原先在服务里各抄一份，共 113 处。
"""

from .contracts import JsonDataError as JsonDataError
from .contracts import JsonDataStatus as JsonDataStatus
from .contracts import JsonEntity as JsonEntity
from .contracts import JsonValue as JsonValue
from .fields import mapping as mapping
from .fields import nonempty_text as nonempty_text
from .fields import nonnegative_int as nonnegative_int
from .fields import positive_int as positive_int
from .schema import ContractSet as ContractSet
from .schema import DefinitionSchemaValidator as DefinitionSchemaValidator
from .schema import SchemaError as SchemaError
from .schema import SchemaValidator as SchemaValidator
from .service import JsonDataService as JsonDataService
from .service import materialize as materialize

__all__ = [
    "ContractSet",
    "DefinitionSchemaValidator",
    "JsonDataError",
    "JsonDataService",
    "JsonDataStatus",
    "JsonEntity",
    "JsonValue",
    "SchemaError",
    "SchemaValidator",
    "mapping",
    "materialize",
    "nonempty_text",
    "nonnegative_int",
    "positive_int",
]
