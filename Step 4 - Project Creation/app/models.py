from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class CreateUserRequest(BaseModel):
    username: str
    full_name: str
    role: str = "standard"
    password: str


class UpdateUserRequest(BaseModel):
    full_name: str | None = None
    role: str | None = None
    status: str | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str


class StoredQueryParam(BaseModel):
    name: str
    label: str
    param_type: str
    placeholder: str = ""
    options: list[str] | None = None
    sort_order: int = 0


class CreateStoredQueryRequest(BaseModel):
    name: str
    description: str = ""
    category: str
    dv_query: str
    params: list[StoredQueryParam] = []


class UpdateStoredQueryRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    dv_query: str | None = None
    params: list[StoredQueryParam] | None = None


class RunQueryRequest(BaseModel):
    param_values: dict[str, str] = {}
    from_date: str = ""
    to_date: str = ""
    force_refresh: bool = False


class BulkDeleteHistoryRequest(BaseModel):
    mode: str
    start_date: str | None = None
    end_date: str | None = None


class CreateFolderRequest(BaseModel):
    name: str
    parent_id: int | None = None


class UpdateFolderRequest(BaseModel):
    name: str | None = None
    parent_id: int | None = None
    sort_order: int | None = None


class ReorderFoldersRequest(BaseModel):
    order: list[int]


class MoveQueryToFolderRequest(BaseModel):
    folder_id: int | None = None


class SaveConfigRequest(BaseModel):
    settings: dict[str, str]


class CreateAIToolRequest(BaseModel):
    keyword: str
    display_name: str
