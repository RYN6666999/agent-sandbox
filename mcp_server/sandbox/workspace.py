"""WorkspaceHandle — 持久 workspace root fd 與 identity 驗證。

Server 啟動時建立 root_fd，之後每次 operation 只 dup 不重新開啟。
每次操作前驗證 root path 的 st_dev/st_ino 未被替換。
"""

import os
import stat
from pathlib import Path


class WorkspaceIdentityChanged(Exception):
    """Workspace root identity 已被替換。"""
    pass


class WorkspaceHandle:
    """持久 workspace root 控制代碼。

    在 server 啟動時建立，持有 root_fd 直到 shutdown。
    每次 operation 前驗證 identity，操作時使用 os.dup(root_fd)。
    """

    def __init__(self, work_dir: str | Path) -> None:
        path = Path(work_dir).resolve()
        if not path.is_dir():
            raise ValueError(f"workspace root not a directory: {path}")
        # 檢查 root 本身是否為 symlink
        if path.is_symlink():
            raise ValueError(f"workspace root is a symlink: {path}")

        self._root_path = path
        self._root_fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self._st = os.fstat(self._root_fd)
        if not stat.S_ISDIR(self._st.st_mode):
            os.close(self._root_fd)
            raise ValueError(f"workspace root not a directory (fstat): {path}")

    @property
    def root_path(self) -> str:
        return str(self._root_path)

    @property
    def root_fd(self) -> int:
        return self._root_fd

    def verify_identity(self) -> None:
        """驗證 workspace root identity 未被替換。

        Raises:
            WorkspaceIdentityChanged: 路徑消失、變成 symlink、或被換成另一個目錄
        """
        try:
            lst = os.lstat(str(self._root_path))
        except FileNotFoundError:
            raise WorkspaceIdentityChanged("workspace root deleted")

        if stat.S_ISLNK(lst.st_mode):
            raise WorkspaceIdentityChanged("workspace root became a symlink")

        if (lst.st_dev, lst.st_ino) != (self._st.st_dev, self._st.st_ino):
            raise WorkspaceIdentityChanged("workspace root identity changed")

    def dup_fd(self) -> int:
        """回傳 root_fd 的 duplicate，供一次 operation 使用。

        Caller 必須在操作完成後關閉此 fd。
        """
        self.verify_identity()
        return os.dup(self._root_fd)

    def close(self) -> None:
        """關閉 root_fd。只應在 server shutdown 時呼叫一次。"""
        if self._root_fd >= 0:
            os.close(self._root_fd)
            self._root_fd = -1