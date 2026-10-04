"""Bounded Telnet console transport. No shell, SSH subprocess or telnetlib dependency."""

from __future__ import annotations

import codecs
import re
import select
import socket
import time
from collections.abc import Callable

from .models import Endpoint, EnspError

IAC, DO, DONT, WILL, WONT, SB, SE = 255, 253, 254, 251, 252, 250, 240
PROMPT = re.compile(r"(?:^|\n)(<([\w.-]{1,64})>|\[([\w./:*-]{1,100})\])\s*$")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
MORE = re.compile(r"-+\s*More\s*-+", re.I)
CLI_ERROR = re.compile(r"(?im)^\s*(?:Error:|%\s*(?:Error|Unrecognized)|Unrecognized command|Incomplete command|Too many parameters)")


def clean_terminal(text: str) -> str:
    text = ANSI.sub("", text).replace("\r", "").replace("\x00", "")
    rendered: list[str] = []
    for char in text:
        if char == "\b":
            if rendered and rendered[-1] != "\n":
                rendered.pop()
        elif char == "\t" or char == "\n" or ord(char) >= 32:
            rendered.append(char)
    return "".join(rendered)


class TelnetCodec:
    """Retains negotiation state across fragmented TCP packets."""

    def __init__(self):
        self.state = "data"
        self.verb = 0
        self.sub = bytearray()

    def feed(self, packet: bytes) -> tuple[bytes, bytes]:
        data, replies = bytearray(), bytearray()
        for byte in packet:
            if self.state == "data":
                if byte == IAC:
                    self.state = "iac"
                else:
                    data.append(byte)
            elif self.state == "iac":
                if byte == IAC:
                    data.append(IAC)
                    self.state = "data"
                elif byte in (DO, DONT, WILL, WONT):
                    self.verb, self.state = byte, "option"
                elif byte == SB:
                    self.sub.clear()
                    self.state = "sub"
                else:
                    self.state = "data"
            elif self.state == "option":
                if self.verb == DO:
                    replies.extend((IAC, WILL if byte in (3, 24, 31) else WONT, byte))
                    if byte == 31:  # NAWS: 200 columns, 24 rows.
                        replies.extend((IAC, SB, 31, 0, 200, 0, 24, IAC, SE))
                elif self.verb == WILL:
                    replies.extend((IAC, DO if byte in (1, 3) else DONT, byte))
                self.state = "data"
            elif self.state == "sub":
                if byte == IAC:
                    self.state = "sub_iac"
                elif len(self.sub) < 1024:
                    self.sub.append(byte)
            elif self.state == "sub_iac":
                if byte == SE:
                    if self.sub == b"\x18\x01":  # TERMINAL-TYPE SEND.
                        replies.extend(bytes((IAC, SB, 24, 0)) + b"VT100" + bytes((IAC, SE)))
                    self.state = "data"
                else:
                    if len(self.sub) < 1024:
                        self.sub.append(byte)
                    self.state = "sub"
        return bytes(data), bytes(replies)


class ConsoleSession:
    def __init__(self, endpoint: Endpoint, timeout: float = 12, encoding: str = "utf-8"):
        self.endpoint, self.timeout, self.encoding = endpoint, timeout, encoding
        self.sock: socket.socket | None = None
        self.codec = TelnetCodec()
        self.prompt = ""
        self.last_output = ""

    def __enter__(self):
        try:
            self.sock = socket.create_connection((self.endpoint.host, self.endpoint.port), timeout=self.timeout)
            self.sock.sendall(b"\r\n")
            self._read_prompt()
            if not self.prompt.startswith("<"):
                raise EnspError("wrong_view", "控制台停留在配置视图，请在 eNSP 控制台执行 return 后重试。")
            return self
        except EnspError:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise EnspError("connection_failed", f"无法连接 {self.endpoint.name} 的本机控制台端口 {self.endpoint.port}：{exc}") from exc

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None

    def _read_prompt(self, on_output: Callable[[str], None] | None = None) -> str:
        if not self.sock:
            raise EnspError("disconnected", "控制台连接已关闭。")
        deadline = time.monotonic() + self.timeout
        decoder = codecs.getincrementaldecoder(self.encoding)(errors="replace")
        text, received, pages = "", 0, 0
        self.last_output = ""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close()
                raise EnspError("timeout", "等待设备提示符超时；结果不完整，不能判定设备正常。")
            self.sock.settimeout(remaining)
            try:
                packet = self.sock.recv(4096)
                if not packet:
                    raise EnspError("disconnected", "设备在返回完整结果前关闭了控制台连接。")
                received += len(packet)
                if received > 262144:
                    raise EnspError("output_limit", "设备输出超过 256 KiB，已中止本次采集。")
                payload, replies = self.codec.feed(packet)
                if replies:
                    self.sock.sendall(replies)
                chunk = decoder.decode(payload)
                text += chunk
                clean = clean_terminal(text)
                self.last_output = clean
                if chunk and on_output:
                    on_output(clean_terminal(chunk))
                if re.search(r"(?im)(?:^|\n)\s*(?:Username|Login|Password)\s*:\s*$", clean):
                    raise EnspError("authentication_required", "此控制台要求登录；当前适配器仅支持预先准备好的本机实验控制台。")
                new_pages = len(MORE.findall(ANSI.sub("", text)))
                if new_pages > pages:
                    self.sock.sendall(b" ")
                    pages = new_pages
                match = PROMPT.search(clean)
                if match:
                    # A console can send its initial prompt and the response to our
                    # wake-up CRLF separately. Drain a brief burst before accepting
                    # the prompt, otherwise that stale prompt can finish the next command.
                    if select.select([self.sock], [], [], min(0.08, max(0, deadline - time.monotonic())))[0]:
                        continue
                    self.prompt = match[1]
                    return clean
            except socket.timeout as exc:
                self.close()
                raise EnspError("timeout", "设备响应超时，已关闭会话；请确认设备已完成启动。") from exc
            except OSError as exc:
                self.close()
                raise EnspError("connection_failed", f"读取控制台失败：{exc}") from exc
            except EnspError:
                self.close()
                raise

    def execute(self, command: str, on_output: Callable[[str], None] | None = None) -> str:
        """Low-level transport; application callers must use the policy in service.py."""
        if not isinstance(command, str) or not command or any(ord(c) < 32 or ord(c) == 127 for c in command):
            raise EnspError("invalid_command", "命令不能包含换行或控制字符。")
        if not self.sock:
            raise EnspError("disconnected", "控制台连接已关闭。")
        self.last_output = ""
        try:
            self.sock.sendall(command.encode(self.encoding).replace(b"\xff", b"\xff\xff") + b"\r\n")
        except OSError as exc:
            self.close()
            raise EnspError("connection_failed", f"发送命令失败：{exc}") from exc
        output = self._read_prompt(on_output)
        if CLI_ERROR.search(output):
            raise EnspError("command_failed", "设备拒绝了该命令；原始错误保留在采集结果中。")
        return output
