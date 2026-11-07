"""audit_upload_zip.py — 上传包「审核器视角」硬闸门。

WorkBuddy 文件质量检测会把文档里点名的**名字**一律当作必须真实存在的资源：
中文名词会被还原成「中文名.py」，带括号英文的短语会被当成目录或文件索要。
历史驳回实例：融合过程对照记录 把被裁文件改名成「摩旅分支模块 / 包内离线数据 /
数据采集脚本」，审核器仍判「内置文件缺失 3 项」。

本模块复现该判据，构建任何平台包后立即全量扫描包内文本，命中即构建失败。
词表用拼接写法，避免本文件万一被收进包时自指命中。
"""
import os
import re
import sys
import zipfile

# 危险词：审核器会把它们还原成文件名并索要
FORBIDDEN = (
    "摩旅" + "路由",
    "本地离线" + "夹具",
    "联网" + "采集模块",
    "离线" + "夹具",
    "专项" + "文档",
    "fix" + "tures/",
    "FUSION" + ".md",
    "UNIFIED_ENTRY" + ".md",
)

# 形态判据：中文名 + .py（驳回项「摩旅分支脚本」的形态）。
# 只查 .py：中文名的 .md 在包里是真实存在的文档（排版规范.md 等），
# 判成缺失属于假阳性，交给 check_refs() 按真实路径核对。
CN_FILE = re.compile(r"[\u4e00-\u9fa5]{2,}\.py")

TEXT_EXT = (".md", ".json", ".py", ".txt", ".yml", ".yaml")
TEXT_NOEXT = {"LICENSE", "LICENCE", "NOTICE"}


def scan(path):
    """扫包内全部文本，返回 (命中列表, 扫描文件数)。

    命中项格式：(包内文件名, 行号, 命中的词/形态, 该行文本片段)
    """
    hits, count = [], 0
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        basenames = {os.path.basename(n) for n in names}
        for name in z.namelist():
            if not name.endswith(TEXT_EXT) and name not in TEXT_NOEXT:
                continue
            count += 1
            text = z.read(name).decode("utf-8", "replace")
            for i, line in enumerate(text.split("\n"), 1):
                found = [tok for tok in FORBIDDEN if tok in line]
                # 中文名 .py 若包内真实存在同名文件，不算缺失
                found += [m.group(0) for m in CN_FILE.finditer(line)
                          if m.group(0) not in basenames]
                for tok in found:
                    hits.append((name, i, tok, line.strip()[:160]))
    seen, uniq = set(), []
    for h in hits:
        key = (h[0], h[1], h[2])
        if key not in seen:
            seen.add(key)
            uniq.append(h)
    return uniq, count


def audit(path, verbose=True):
    """返回 True 表示可提交；任何命中都判 BLOCKER。"""
    hits, count = scan(path)
    if verbose:
        print("  审核器视角: 扫描 %d 个文本文件，危险命中 %d 条" % (count, len(hits)))
        for h in hits[:20]:
            print("    BLOCKER %s:%d [%s] %s" % h)
        if len(hits) > 20:
            print("    ... 另有 %d 条" % (len(hits) - 20))
    return not hits


def assert_clean(path):
    if not audit(path):
        raise RuntimeError("上传包审核器视角自检失败: %s" % path)
    return True


if __name__ == "__main__":
    paths = sys.argv[1:]
    if not paths:
        print("用法: python tools/audit_upload_zip.py <包1.zip> [包2.zip ...]")
        sys.exit(2)
    ok = True
    for p in paths:
        print("=== %s ===" % p)
        ok = audit(p) and ok
    print("AUDIT: %s" % ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)
