"""正式 JSON 数据核心微服务。

除正式数据快照外，本包还公开字段契约（schema）的通用校验引擎：各领域服务
用它校验自己拥有的 JSON 是否符合已声明的字段契约，避免各自手写一遍类型与
引用检查。契约的书写约定见 `data/schema编写规范.md`。
"""

from .contracts import JsonDataError as JsonDataError
from .contracts import JsonDataStatus as JsonDataStatus
from .contracts import JsonEntity as JsonEntity
from .contracts import JsonValue as JsonValue
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
    "materialize",
]
