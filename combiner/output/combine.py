"""
combine.py - combine RTF tables into one Word document.

Double-click combine.bat to open the window, or run from a command prompt:

    combine.bat --run --folder ..\\input --study CDISCPILOT01 --title "Section 14 Summary Tables"

What it does
  * Lists every .rtf in a folder with its table number, title and page layout.
  * You tick the tables to include and set their order.
  * Microsoft Word (driven through pywin32) builds one .docx:
      - title page (study, report title, date, list of tables)
      - contents page with clickable links and page numbers
      - each table in its own section, keeping its own page size, orientation,
        margins, page header (titles and column headers) and footer (notes)
  * Each table keeps its own "Page X of Y": the PAGE / NUMPAGES fields in its
    header are rewritten so they count that table's pages only.
  * An overall "Page X of Y" for the whole document is added in the footer.
  * The page count of every table is checked against the stand-alone RTF and
    everything is written to a run log next to the .docx.

The input RTF files are never changed: Word only opens temporary copies of them.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "1.0"
APP_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "combine_settings.json"
DOC_FONT = "Courier New"          # font used for the title and contents pages

# --------------------------------------------------------------------------
# Word constants (from the Word object model)
# --------------------------------------------------------------------------
wdCollapseEnd = 0
wdSectionBreakNextPage = 2
wdFieldEmpty = -1
wdFieldNumPages = 26
wdFieldPage = 33
wdFieldSectionPages = 47
wdStatisticPages = 2
wdActiveEndPageNumber = 3
wdFormatDocumentDefault = 16
wdDoNotSaveChanges = 0
wdOrientPortrait = 0
wdAlignParagraphLeft = 0
wdAlignParagraphCenter = 1
wdAlignParagraphRight = 2
wdAlignTabLeft = 0
wdAlignTabRight = 2
wdTabLeaderSpaces = 0
wdTabLeaderDots = 1
wdLineSpaceSingle = 0
wdLineSpaceExactly = 4
wdWithInTable = 12
wdRelativeHorizontalPositionMargin = 0
wdRelativeVerticalPositionPage = 1
wdWrapFront = 3
wdColorAutomatic = -16777216
msoTextOrientationHorizontal = 1
HF_KINDS = (1, 2, 3)              # primary, first page, even pages


# --------------------------------------------------------------------------
# Reading table number / title straight from the RTF (no Word needed)
# --------------------------------------------------------------------------
_RTF_TOKEN = re.compile(
    r"\\([a-zA-Z]+)(-?\d+)? ?"      # control word
    r"|\\'([0-9a-fA-F]{2})"         # hex character
    r"|\\(.)"                       # control symbol
    r"|([{}])"                      # group
    r"|[\r\n]+"                     # raw newlines are not text in RTF
    r"|([^\\{}\r\n]+)",             # plain text
    re.S,
)
_SKIP_DESTINATIONS = {
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "fldinst",
    "themedata", "colorschememapping", "datastore", "latentstyles", "listtable",
    "listoverridetable", "rsidtbl", "generator", "xmlnstbl", "mmathPr",
    "filetbl", "revtbl", "pgdsctbl", "nonshppict", "shppict", "footer",
    "footerl", "footerr", "footerf", "footnote", "bkmkstart", "bkmkend",
}
_RTF_SPECIAL = {
    "par": "\n", "line": "\n", "row": "\n", "sect": "\n", "page": "\n",
    "cell": "\x07", "tab": "\t", "emdash": "\u2014", "endash": "\u2013",
    "lquote": "\u2018", "rquote": "\u2019", "ldblquote": "\u201c",
    "rdblquote": "\u201d", "bullet": "\u2022",
}


def rtf_to_text(data: str) -> str:
    """Very small RTF-to-text converter, good enough to find titles.
    Cell ends become \\x07 so a title can be cut at the end of its cell."""
    out: list[str] = []
    stack: list[tuple[bool, int]] = []
    ignore, uc, skip = False, 1, 0
    for m in _RTF_TOKEN.finditer(data):
        word, arg, hexc, sym, brace, text = m.groups()
        if brace:
            if brace == "{":
                stack.append((ignore, uc))
            elif stack:
                ignore, uc = stack.pop()
            skip = 0
            continue
        if word:
            if word in _SKIP_DESTINATIONS:
                ignore = True
            elif ignore:
                continue
            elif word == "uc":
                uc = int(arg or 1)
            elif word == "u":
                code = int(arg or 0)
                out.append(chr(code + 65536 if code < 0 else code))
                skip = uc
            elif word in _RTF_SPECIAL:
                out.append(_RTF_SPECIAL[word])
            continue
        if sym:
            if sym == "*":
                ignore = True
            elif not ignore:
                if skip:
                    skip -= 1
                elif sym in "\\{}":
                    out.append(sym)
                elif sym == "~":
                    out.append(" ")
                elif sym == "_":
                    out.append("-")
            continue
        if ignore:
            continue
        if hexc:
            if skip:
                skip -= 1
            else:
                out.append(bytes([int(hexc, 16)]).decode("cp1252", "replace"))
            continue
        if text:
            if skip:
                cut = min(skip, len(text))
                text, skip = text[cut:], skip - cut
            out.append(text)
    return "".join(out)


_NUM_RE = re.compile(r"\b(Table|Listing|Figure)\s+(\d+(?:\.\d+)*[A-Za-z]?\d*)")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


@dataclass
class TableInfo:
    path: Path
    number: str = ""
    kind: str = "Table"
    title: str = ""
    layout: str = ""
    include: bool = True
    error: str = ""
    # filled during the build
    pages_alone: int = 0
    first_page: int = 0
    last_page: int = 0
    bookmark: str = ""
    fields_converted: int = 0
    orientation_ok: bool = True
    checks: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.kind} {self.number}" if self.number else self.path.stem

    def sort_key(self):
        if not self.number:
            return (1, (), self.path.name.lower())
        parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p.lower())
                      for p in re.findall(r"\d+|[A-Za-z]+", self.number))
        return (0, parts, self.path.name.lower())


def scan_rtf(path: Path) -> TableInfo:
    info = TableInfo(path=path)
    try:
        raw = path.read_bytes()[:400_000].decode("cp1252", errors="replace")
        head = raw[:4000]
        pw = re.search(r"\\paperw(\d+)", head)
        ph = re.search(r"\\paperh(\d+)", head)
        landscape = bool(re.search(r"\\landscape\b|\\lndscpsxn", head)) or (
            pw and ph and int(pw.group(1)) > int(ph.group(1)))
        info.layout = "Landscape" if landscape else "Portrait"
        text = rtf_to_text(raw)
        m = _NUM_RE.search(text)
        if m:
            info.kind, info.number = m.group(1), m.group(2)
            seg = re.split(r"\x07|\n[ \t]*\n", text[m.end():], maxsplit=1)[0]
            lines = [_clean(x) for x in seg.split("\n")]
            lines = [x for x in lines if x][:4]
            if lines:
                info.title = lines[0] + (f" ({'; '.join(lines[1:])})" if len(lines) > 1 else "")
        if not info.title:
            info.title = path.stem
    except Exception as exc:          # unreadable file: still list it
        info.error = str(exc)
        info.title = path.stem
    return info


def scan_folder(folder: Path) -> list[TableInfo]:
    files = sorted(p for p in Path(folder).glob("*.rtf") if p.is_file())
    return sorted((scan_rtf(p) for p in files), key=TableInfo.sort_key)


def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# Small Word helpers
# --------------------------------------------------------------------------
def _story_end(full_range):
    """Collapsed range just before the final paragraph mark of a story."""
    r = full_range.Duplicate
    r.SetRange(full_range.End - 1, full_range.End - 1)
    return r


def _add_field(at_range, code: str):
    return at_range.Fields.Add(at_range, wdFieldEmpty, code, False)


def _add_nested_field(at_range, parts):
    """Insert { = part part ... } at a collapsed range.
    parts: plain strings are typed into the code, ("F", code) items become
    nested fields.  Returns the outer Field."""
    outer = at_range.Fields.Add(at_range, wdFieldEmpty, "= ", False)
    for part in parts:
        c = outer.Code
        c.Collapse(wdCollapseEnd)
        if isinstance(part, tuple):
            c.Fields.Add(c, wdFieldEmpty, part[1], False)
        else:
            c.InsertAfter(part)
    return outer


def _whole_field_range(story_range, fld):
    r = story_range.Duplicate
    r.SetRange(fld.Code.Start - 1, fld.Result.End + 1)
    return r


def _copy_font(src_font, dst_font):
    for attr in ("Name", "Size", "Bold", "Italic", "Underline", "Color",
                 "Superscript", "Subscript"):
        try:
            setattr(dst_font, attr, getattr(src_font, attr))
        except Exception:
            pass




def _copy_last_paragraph_look(src_para, dst_para):
    try:
        dst_para.Style = src_para.Style.NameLocal
    except Exception:
        pass
    try:
        dst_para.Format = src_para.Format
    except Exception:
        pass
    _copy_font(src_para.Range.Font, dst_para.Range.Font)


def _compat_flags(doc) -> dict:
    """Word's layout compatibility switches (Document.Compatibility(n))."""
    flags = {}
    for i in range(0, 120):
        try:
            flags[i] = bool(doc.Compatibility(i))
        except Exception:
            pass
    return flags




def _make_paragraph_take_no_space(para):
    f = para.Range.Font
    f.Hidden = True
    f.Size = 1
    pf = para.Format
    pf.SpaceBefore = 0
    pf.SpaceAfter = 0
    pf.LineSpacingRule = wdLineSpaceExactly
    pf.LineSpacing = 1


def _clear_story(hf):
    """Empty a header/footer that was inherited from the previous section."""
    r = hf.Range
    try:   # floating shapes (e.g. the overall page box)
        if r.ShapeRange.Count:
            r.ShapeRange.Delete()
    except Exception:
        pass
    while hf.Range.Tables.Count:
        hf.Range.Tables(1).Delete()
    r = hf.Range
    if r.End - r.Start > 1:
        x = r.Duplicate
        x.SetRange(r.Start, r.End - 1)
        x.Delete()
    last = hf.Range.Paragraphs.Last
    last.Range.Font.Reset()
    last.Format.Reset()


def _copy_story(src_hf, dst_hf):
    """Copy a header/footer so it is exactly as tall as the original.

    Every Word story ends with its own paragraph mark.  Two cases:
      * the source ends with a normal paragraph (the footers): copy all but
        that final mark and give the target's final mark its formatting;
      * the source ends inside a table with no paragraph after it (the gt
        page headers - allowed in RTF, not in .docx): copy everything and
        make the target's compulsory final paragraph hidden and 1pt high,
        so the header is no taller than in the stand-alone RTF."""
    s_all = src_hf.Range
    ends_in_table = bool(s_all.Paragraphs.Last.Range.Information(wdWithInTable))
    src = s_all.Duplicate
    if not ends_in_table:
        src.SetRange(s_all.Start, s_all.End - 1)
    _clear_story(dst_hf)
    if src.End > src.Start:
        d_all = dst_hf.Range
        dst = d_all.Duplicate
        dst.SetRange(d_all.Start, d_all.Start)
        dst.FormattedText = src.FormattedText
    if ends_in_table:
        _make_paragraph_take_no_space(dst_hf.Range.Paragraphs.Last)
    else:
        _copy_last_paragraph_look(src_hf.Range.Paragraphs.Last,
                                  dst_hf.Range.Paragraphs.Last)


def _copy_page_setup(src, dst):
    dst.Orientation = src.Orientation
    for attr in ("PageWidth", "PageHeight", "TopMargin", "BottomMargin",
                 "LeftMargin", "RightMargin", "Gutter", "HeaderDistance",
                 "FooterDistance", "VerticalAlignment",
                 "DifferentFirstPageHeaderFooter", "OddAndEvenPagesHeaderFooter"):
        try:
            setattr(dst, attr, getattr(src, attr))
        except Exception:
            pass
    dst.SectionStart = wdSectionBreakNextPage


def _bookmark_name(info: TableInfo, used: set) -> str:
    base = "T_" + re.sub(r"[^A-Za-z0-9]", "_", info.number or info.path.stem)
    base = base[:34]
    name, n = base, 2
    while name.lower() in used:
        name = f"{base[:30]}_{n}"
        n += 1
    used.add(name.lower())
    return name


def _hf_kinds_in_use(page_setup):
    kinds = [1]
    if page_setup.DifferentFirstPageHeaderFooter:
        kinds.append(2)
    if page_setup.OddAndEvenPagesHeaderFooter:
        kinds.append(3)
    return kinds


# --------------------------------------------------------------------------
# The build
# --------------------------------------------------------------------------
class Builder:
    def __init__(self, items, study, title, out_path, log, date=None):
        self.items = [i for i in items if i.include]
        self.study = study.strip()
        self.title = title.strip()
        self.out_path = Path(out_path).resolve()
        self.log = log
        self.date = date or dt.date.today()
        self.word = None
        self.doc = None
        self.tmpdir = None
        self.compat_flags = {}
        self.total_pages = 0
        self.front_pages = 0
        self.problems: list[str] = []

    # ---- entry point --------------------------------------------------
    def run(self) -> bool:
        """Build once; if Word stops responding part-way (it occasionally
        rejects calls while busy laying out a long table), start again once
        with a fresh copy of Word.  Nothing is saved until the end."""
        if not self.items:
            raise ValueError("No tables are ticked.")
        import pythoncom
        pythoncom.CoInitialize()
        try:
            for attempt in (1, 2):
                try:
                    return self._run_once()
                except (pythoncom.com_error, AttributeError) as exc:
                    if attempt == 2:
                        raise
                    self.log(f"Word stopped responding ({exc}); "
                             f"starting again with a fresh copy of Word")
                    self._reset()
        finally:
            pythoncom.CoUninitialize()

    def _reset(self):
        self.problems = []
        for it in self.items:
            it.fields_converted = 0
            it.orientation_ok = True

    def _run_once(self) -> bool:
        import win32com.client
        before = _word_pids()
        self.log("Starting Microsoft Word (separate hidden instance)")
        self.word = win32com.client.DispatchEx("Word.Application")
        new = _word_pids() - before
        my_pid = new.pop() if len(new) == 1 else None
        quit_ok = False
        try:
            self.word.Visible = False
            self.word.DisplayAlerts = 0
            for opt, val in (("ScreenUpdating", False),):
                try:
                    setattr(self.word, opt, val)
                except Exception:
                    pass
            try:
                self.word.Options.Pagination = False   # no background layout
            except Exception:
                pass
            self.log(f"Word version {self.word.Version}")
            self._build()
            self._finish_fields()
            self._check()
            self._save()
            return not self.problems
        finally:
            try:
                if self.doc is not None:
                    self.doc.Close(wdDoNotSaveChanges)
            except Exception:
                pass
            try:
                self.word.Quit(wdDoNotSaveChanges)
                quit_ok = True
            except Exception:
                pass
            self.doc = self.word = None
            if not quit_ok and my_pid:
                _kill_pid(my_pid)   # never leave a hidden Word running
            if self.tmpdir:
                shutil.rmtree(self.tmpdir, ignore_errors=True)
                self.tmpdir = None

    def _open_source(self, path: Path):
        """Word opens a temporary copy, so it never touches the input folder
        (not even for its own lock or temp files)."""
        copy = self.tmpdir / "sources" / path.name
        copy.parent.mkdir(exist_ok=True)
        shutil.copyfile(path, copy)
        return self.word.Documents.Open(
            FileName=str(copy), ConfirmConversions=False, ReadOnly=True,
            AddToRecentFiles=False, Visible=False)

    # ---- document body --------------------------------------------------
    def _build(self):
        used_bm: set = set()
        for it in self.items:
            it.bookmark = _bookmark_name(it, used_bm)
        self.tmpdir = Path(tempfile.mkdtemp(prefix="rtfcombine_"))

        for idx, it in enumerate(self.items, start=1):
            self.log(f"[{idx}/{len(self.items)}] {it.path.name}: {it.label}")
            src = self._open_source(it.path)
            try:
                src.Repaginate()
                it.pages_alone = int(src.ComputeStatistics(wdStatisticPages))
                self.log(f"    stand-alone in Word: {it.pages_alone} page(s), "
                         f"{src.Sections.Count} section(s)")
                if self.doc is None:
                    self._start_document(src, it.path)
                else:
                    diff = [k for k, v in _compat_flags(src).items()
                            if self.compat_flags.get(k) != v]
                    if diff or int(src.CompatibilityMode) != int(self.doc.CompatibilityMode):
                        self.log(f"    note: this file's Word layout options differ from "
                                 f"the first file's ({len(diff)} option(s)); the page "
                                 f"check below will show if that matters")
                self._append_table(src, it)
            finally:
                src.Close(wdDoNotSaveChanges)

    def _start_document(self, first_src, first_path: Path):
        """The combined document starts life as a .docx copy of the first RTF
        (made in a temporary folder), emptied out.  That way it inherits all
        of Word's document-level layout settings for these RTF files -
        compatibility mode and options, character spacing, base styles.  A
        blank new document lays text out slightly differently (for example
        it does not squeeze spaces to fit a full table cell), which can move
        a row onto the next page."""
        rtf_copy = self.tmpdir / ("base_" + first_path.name)
        shutil.copyfile(first_path, rtf_copy)
        base = self.word.Documents.Open(FileName=str(rtf_copy), ConfirmConversions=False,
                                        ReadOnly=False, AddToRecentFiles=False,
                                        Visible=False)
        base.SaveAs2(FileName=str(self.tmpdir / "base.docx"),
                     FileFormat=wdFormatDocumentDefault)
        doc = self.doc = base
        doc.Content.Delete()
        while doc.Tables.Count:
            doc.Tables(1).Delete()
        doc.Content.Delete()
        sec = doc.Sections(1)
        for kind in HF_KINDS:
            _clear_story(sec.Headers(kind))
            _clear_story(sec.Footers(kind))
        last = doc.Paragraphs.Last
        last.Range.Font.Reset()
        last.Format.Reset()
        self.compat_flags = _compat_flags(first_src)
        self.log(f"    combined document started from an emptied .docx copy of this "
                 f"file (Word compatibility mode {doc.CompatibilityMode}, same "
                 f"layout settings as the RTF)")

        # Front matter: portrait version of the tables' paper size.
        ps_src = first_src.Sections(1).PageSetup
        ps = doc.Sections(1).PageSetup
        ps.Orientation = wdOrientPortrait
        ps.PageWidth = min(ps_src.PageWidth, ps_src.PageHeight)
        ps.PageHeight = max(ps_src.PageWidth, ps_src.PageHeight)
        for attr in ("TopMargin", "BottomMargin", "LeftMargin", "RightMargin"):
            setattr(ps, attr, 72)
        ps.HeaderDistance = ps.FooterDistance = 36
        doc.Sections(1).Headers(1).PageNumbers.RestartNumberingAtSection = False
        self._front_matter()

    def _para(self, text, size=11, bold=False, align=wdAlignParagraphLeft,
              before=0, after=6, tabs=(), left_indent=0, first_indent=0):
        doc = self.doc
        r = _story_end(doc.Content)
        r.InsertAfter(text)
        p = r.Paragraphs(1)
        p.Range.Font.Name = DOC_FONT
        p.Range.Font.Size = size
        p.Range.Font.Bold = bold
        p.Range.Font.Italic = False
        f = p.Format
        f.Alignment = align
        f.SpaceBefore = before
        f.SpaceAfter = after
        f.LineSpacingRule = wdLineSpaceSingle
        f.LeftIndent = left_indent
        f.FirstLineIndent = first_indent
        f.TabStops.ClearAll()
        for pos, kind, leader in tabs:
            f.TabStops.Add(pos, kind, leader)
        start = r.Start
        r.InsertParagraphAfter()
        return start      # Paragraph objects shift after inserts, positions do not

    def _para_range(self, pos):
        return self.doc.Range(pos, pos).Paragraphs(1).Range

    def _front_matter(self):
        doc = self.doc
        ps = doc.Sections(1).PageSetup
        width = ps.PageWidth - ps.LeftMargin - ps.RightMargin
        hang = 108  # 1.5 inch for "Table 14.3.3.1a"

        # --- title page
        self._para(self.study, size=20, bold=True, align=wdAlignParagraphCenter,
                   before=150, after=18)
        self._para(self.title, size=16, bold=True, align=wdAlignParagraphCenter,
                   after=18)
        self._para(self.date.strftime("%d %B %Y").lstrip("0"), size=12,
                   align=wdAlignParagraphCenter, after=60)
        self._para(f"Tables included ({len(self.items)})", size=12, bold=True,
                   after=8)
        for it in self.items:
            self._para(f"{it.label}\t{it.title}", size=10, after=4,
                       tabs=[(hang, wdAlignTabLeft, wdTabLeaderSpaces)],
                       left_indent=hang, first_indent=-hang)
        # --- contents page
        pos = self._para("Contents", size=14, bold=True, after=14)
        self._para_range(pos).ParagraphFormat.PageBreakBefore = True
        self._para("Table\tTitle\tPage", size=10, bold=True, after=8,
                   tabs=[(hang, wdAlignTabLeft, wdTabLeaderSpaces),
                         (width, wdAlignTabRight, wdTabLeaderSpaces)],
                   left_indent=hang, first_indent=-hang)
        for it in self.items:
            pos = self._para(f"{it.label}\t{it.title}\t", size=10, after=6,
                             tabs=[(hang, wdAlignTabLeft, wdTabLeaderSpaces),
                                   (width, wdAlignTabRight, wdTabLeaderDots)],
                             left_indent=hang, first_indent=-hang)
            # clickable text (everything up to the last tab)
            pr = self._para_range(pos)
            link = doc.Range(pr.Start, pr.End - 2)
            hl = doc.Hyperlinks.Add(Anchor=link, Address="", SubAddress=it.bookmark,
                                    ScreenTip=f"Go to {it.label}")
            hr = hl.Range
            hr.Font.Color = wdColorAutomatic
            hr.Font.Underline = 0
            # page number: PAGEREF with \h is itself a link
            pend = self._para_range(pos).End - 1
            at = doc.Range(pend, pend)
            _add_field(at, f"PAGEREF {it.bookmark} \\h")
        self._add_overall_pager(doc.Sections(1))

    # ---- one table -------------------------------------------------------
    def _append_table(self, src, it: TableInfo):
        doc = self.doc
        n_src = src.Sections.Count
        first_sec = None
        for si in range(1, n_src + 1):
            ssec = src.Sections(si)
            r = _story_end(doc.Content)
            r.InsertBreak(wdSectionBreakNextPage)
            tsec = doc.Sections(doc.Sections.Count)
            first_sec = first_sec or tsec
            _copy_page_setup(ssec.PageSetup, tsec.PageSetup)
            tsec.Headers(1).PageNumbers.RestartNumberingAtSection = False
            if tsec.PageSetup.Orientation != ssec.PageSetup.Orientation:
                it.orientation_ok = False

            # page header (titles + column headers) and footer (notes)
            for kind in HF_KINDS:
                for coll in ("Headers", "Footers"):
                    th = getattr(tsec, coll)(kind)
                    sh = getattr(ssec, coll)(kind)
                    th.LinkToPrevious = False
                    _copy_story(sh, th)

            # table body (everything except the section's final mark)
            sr = ssec.Range
            body = src.Range(sr.Start, sr.End - 1)
            dest = _story_end(doc.Content)
            dest.FormattedText = body.FormattedText

            # the paragraph that will hold the next section break should look
            # like the RTF's last paragraph (it can affect the page count)
            _copy_last_paragraph_look(sr.Paragraphs.Last, doc.Paragraphs.Last)

        # bookmarks marking where the table starts and ends
        sec_last = doc.Sections(doc.Sections.Count)
        start = doc.Range(first_sec.Range.Start, first_sec.Range.Start)
        end = doc.Range(sec_last.Range.End - 1, sec_last.Range.End - 1)
        doc.Bookmarks.Add(it.bookmark, start)
        doc.Bookmarks.Add(it.bookmark + "_end", end)

        # rewrite page fields so they count this table's pages only
        for si in range(first_sec.Index, sec_last.Index + 1):
            tsec = doc.Sections(si)
            for kind in HF_KINDS:
                for coll in ("Headers", "Footers"):
                    it.fields_converted += self._convert_page_fields(
                        getattr(tsec, coll)(kind), it.bookmark)
            self._add_overall_pager(tsec)
        self.log(f"    copied: layout {it.layout.lower()}, "
                 f"{it.fields_converted} page field(s) set to count this table only")

    def _convert_page_fields(self, hf, bm) -> int:
        story = hf.Range
        targets = [story.Fields(i) for i in range(1, story.Fields.Count + 1)]
        targets = [f for f in targets
                   if f.Type in (wdFieldPage, wdFieldNumPages, wdFieldSectionPages)]
        done = 0
        for fld in reversed(targets):
            ftype = fld.Type
            switches = " ".join(re.findall(r"\\\*\s*\w+", fld.Code.Text))
            fmt_src = fld.Result.Duplicate
            font = {}
            for attr in ("Name", "Size", "Bold", "Italic", "Underline", "Color"):
                try:
                    font[attr] = getattr(fmt_src.Font, attr)
                except Exception:
                    pass
            pos = fld.Code.Start - 1
            fld.Delete()
            at = story.Duplicate
            at.SetRange(pos, pos)
            if ftype == wdFieldPage:   # page within this table
                parts = [("F", "PAGE"), " - ", ("F", f"PAGEREF {bm}"), " + 1"]
            else:                      # number of pages in this table
                parts = [("F", f"PAGEREF {bm}_end"), " - ", ("F", f"PAGEREF {bm}"), " + 1"]
            outer = _add_nested_field(at, parts + [f" \\# 0 {switches}".rstrip()])
            whole = _whole_field_range(story, outer)
            for attr, val in font.items():
                try:
                    setattr(whole.Font, attr, val)
                except Exception:
                    pass
            done += 1
        return done

    def _add_overall_pager(self, sec):
        """Overall 'Page X of Y' in a floating text box at the foot of the
        page, below the footer notes, so it takes no space from the table
        (adding a footer line would push rows onto extra pages)."""
        ps = sec.PageSetup
        width = ps.PageWidth - ps.LeftMargin - ps.RightMargin
        for kind in _hf_kinds_in_use(ps):
            ftr = sec.Footers(kind)
            anchor = ftr.Range.Paragraphs(1).Range
            anchor.Collapse(1)
            shp = ftr.Shapes.AddTextbox(msoTextOrientationHorizontal, 0, 0,
                                        width, 14, anchor)
            shp.Name = f"OverallPage_{sec.Index}_{kind}"
            shp.WrapFormat.Type = wdWrapFront
            shp.RelativeHorizontalPosition = wdRelativeHorizontalPositionMargin
            shp.RelativeVerticalPosition = wdRelativeVerticalPositionPage
            shp.Left = 0
            shp.Top = ps.PageHeight - ps.FooterDistance + 4
            shp.Line.Visible = 0
            shp.Fill.Visible = 0
            tf = shp.TextFrame
            tf.MarginLeft = tf.MarginRight = tf.MarginTop = tf.MarginBottom = 0
            tr = tf.TextRange
            tr.Text = "Overall Page "
            _add_field(_story_end_text(tf), "PAGE")
            _story_end_text(tf).InsertAfter(" of ")
            _add_field(_story_end_text(tf), "NUMPAGES")
            tr = tf.TextRange
            tr.Font.Name = DOC_FONT
            tr.Font.Size = 9
            tr.Font.Italic = False
            tr.Font.Bold = False
            pf = tr.ParagraphFormat
            pf.Alignment = wdAlignParagraphRight
            pf.SpaceBefore = pf.SpaceAfter = 0
            pf.LineSpacingRule = wdLineSpaceSingle

    # ---- fields, checks, save ------------------------------------------
    def _update_all_fields(self):
        doc = self.doc
        doc.Repaginate()
        for story in doc.StoryRanges:
            s = story
            while s is not None:
                try:
                    s.Fields.Update()
                except Exception:
                    pass
                try:
                    s = s.NextStoryRange
                except Exception:
                    s = None

    def _finish_fields(self):
        self.log("Updating page numbers, contents and page fields")
        self._update_all_fields()
        self._update_all_fields()   # second pass: contents page numbers settle

    def _check(self):
        doc = self.doc
        doc.Repaginate()
        self.total_pages = int(doc.ComputeStatistics(wdStatisticPages))
        self.log("Checks")
        prev_last = None
        for it in self.items:
            s = int(doc.Bookmarks(it.bookmark).Range.Information(wdActiveEndPageNumber))
            e = int(doc.Bookmarks(it.bookmark + "_end").Range.Information(wdActiveEndPageNumber))
            it.first_page, it.last_page = s, e
            n = e - s + 1
            it.checks = {
                "page count matches stand-alone RTF": n == it.pages_alone,
                "starts on a new page straight after the previous table":
                    prev_last is None or s == prev_last + 1,
                "orientation kept": it.orientation_ok,
                "page fields found and converted": it.fields_converted >= 2,
            }
            prev_last = e
            for name, ok in it.checks.items():
                if not ok:
                    self.problems.append(f"{it.label}: {name} FAILED")
            self.log(f"    {it.label:<20} stand-alone {it.pages_alone:>3}  combined "
                     f"{n:>3} (document pages {s}-{e})  "
                     + ("OK" if all(it.checks.values()) else "PROBLEM"))
        self.front_pages = self.items[0].first_page - 1
        expected = self.front_pages + sum(i.pages_alone for i in self.items)
        ok_total = self.total_pages == expected
        if not ok_total:
            self.problems.append(
                f"Total pages {self.total_pages} != front pages {self.front_pages} "
                f"+ table pages {expected - self.front_pages}")
        self.log(f"    title + contents pages: {self.front_pages}; "
                 f"total document pages: {self.total_pages} "
                 f"(expected {expected}) " + ("OK" if ok_total else "PROBLEM"))

    def _save(self):
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        if self.out_path.exists():
            try:
                with open(self.out_path, "r+b"):
                    pass
            except OSError:
                raise RuntimeError(f"{self.out_path.name} is open in another program "
                                   f"(close it in Word and try again)")
        self.doc.SaveAs2(FileName=str(self.out_path), FileFormat=wdFormatDocumentDefault)
        self.log(f"Saved {self.out_path}")


def _word_pids() -> set:
    """Process ids of running Word instances (to tidy up our own if needed)."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq WINWORD.EXE", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return {int(r[1]) for r in csv.reader(out.splitlines())
                if len(r) > 1 and r[1].isdigit()}
    except Exception:
        return set()


def _kill_pid(pid: int):
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                       timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass


def _story_end_text(text_frame):
    return _story_end(text_frame.TextRange)


# --------------------------------------------------------------------------
# Run + log (shared by the window and the command line)
# --------------------------------------------------------------------------
def run_combine(items, study, title, out_path, emit=print, date=None):
    """Builds the document and writes <out>_log.txt. Returns (ok, log_path, builder)."""
    out_path = Path(out_path).resolve()
    log_path = out_path.with_name(out_path.stem + "_log.txt")
    lines: list[str] = []

    def log(msg=""):
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        line = f"{stamp}  {msg}"
        lines.append(line)
        emit(line)

    chosen = [i for i in items if i.include]
    hdr = [
        "RTF COMBINER - RUN LOG",
        "=" * 70,
        f"Run at        : {dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Program       : {Path(__file__).resolve()} (version {VERSION})",
        f"Python        : {sys.version.split()[0]}",
        f"Study         : {study}",
        f"Report title  : {title}",
        f"Output        : {out_path}",
        f"Tables chosen : {len(chosen)}",
        "",
        "Inputs (in document order)",
        "-" * 70,
    ]
    for n, it in enumerate(chosen, 1):
        st = it.path.stat()
        hdr += [f"{n:>2}. {it.label} - {it.title}",
                f"    file   : {it.path}",
                f"    layout : {it.layout}; size {st.st_size:,} bytes; modified "
                f"{dt.datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M:%S}",
                f"    md5    : {md5(it.path)}"]
    hdr += ["", "Steps", "-" * 70]
    for h in hdr:
        emit(h)

    builder = Builder(items, study, title, out_path, log, date=date)
    ok = False
    try:
        ok = builder.run()
        log("")
        if ok:
            log(f"RESULT: PASS - {len(chosen)} table(s), {builder.total_pages} pages; "
                f"every table has the same number of pages as on its own.")
        else:
            log("RESULT: CHECK FAILED")
            for p in builder.problems:
                log(f"    - {p}")
    except Exception as exc:
        log(f"RESULT: ERROR - {exc}")
        for tl in traceback.format_exc().rstrip().splitlines():
            lines.append("        " + tl)
    finally:
        log_path.write_text("\n".join(hdr + lines) + "\n", encoding="utf-8")
    return ok, log_path, builder


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
def load_settings() -> dict:
    default_folder = APP_DIR.parent / "input"
    s = {"folder": str(default_folder if default_folder.is_dir() else APP_DIR),
         "study": "CDISCPILOT01", "title": "Section 14 Summary Tables",
         "output": ""}
    try:
        s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return s


def save_settings(s: dict):
    try:
        SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")
    except Exception:
        pass


def default_output(study: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]+', "_", study.strip() or "combined")
    return str(APP_DIR / f"{safe}_tables.docx")


# --------------------------------------------------------------------------
# The window
# --------------------------------------------------------------------------
def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    TICK, NOTICK = "\u2611", "\u2610"

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("RTF table combiner")
            self.geometry("1050x680")
            self.minsize(820, 520)
            self.settings = load_settings()
            self.items: list[TableInfo] = []
            self.q: queue.Queue = queue.Queue()
            self.busy = False

            self.var_folder = tk.StringVar(value=self.settings["folder"])
            self.var_study = tk.StringVar(value=self.settings["study"])
            self.var_title = tk.StringVar(value=self.settings["title"])
            self.var_out = tk.StringVar(value=self.settings.get("output")
                                        or default_output(self.settings["study"]))
            self.var_status = tk.StringVar(value="")
            self._build_ui()
            self.refresh()
            self.after(150, self._poll)

        # ---- layout
        def _build_ui(self):
            pad = dict(padx=6, pady=4)
            top = ttk.Frame(self)
            top.pack(fill="x", **pad)
            ttk.Label(top, text="Folder with RTF tables:").pack(side="left")
            ttk.Entry(top, textvariable=self.var_folder).pack(side="left", fill="x",
                                                               expand=True, padx=4)
            ttk.Button(top, text="Browse\u2026", command=self.browse).pack(side="left")
            ttk.Button(top, text="Refresh", command=self.refresh).pack(side="left", padx=4)

            mid = ttk.Frame(self)
            mid.pack(fill="both", expand=True, **pad)
            cols = ("inc", "num", "title", "layout", "file")
            self.tree = ttk.Treeview(mid, columns=cols, show="headings",
                                     selectmode="browse", height=12)
            for c, text, w, st in (("inc", "Include", 60, False),
                                   ("num", "Table", 110, False),
                                   ("title", "Title", 480, True),
                                   ("layout", "Layout", 80, False),
                                   ("file", "File", 220, True)):
                self.tree.heading(c, text=text)
                self.tree.column(c, width=w, stretch=st,
                                 anchor="center" if c in ("inc", "layout") else "w")
            sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
            self.tree.configure(yscrollcommand=sb.set)
            self.tree.bind("<Button-1>", self._on_click)
            self.tree.bind("<space>", lambda e: self.toggle_selected())
            self.tree.bind("<Control-Up>", lambda e: (self.move(-1), "break")[1])
            self.tree.bind("<Control-Down>", lambda e: (self.move(1), "break")[1])

            side = ttk.Frame(mid)   # packed first so the buttons never get squeezed
            side.pack(side="right", fill="y", padx=(8, 0))
            sb.pack(side="right", fill="y")
            self.tree.pack(side="left", fill="both", expand=True)
            for text, cmd in (("Move up", lambda: self.move(-1)),
                              ("Move down", lambda: self.move(1)),
                              ("Sort by table number", self.sort_items),
                              (None, None),
                              ("Tick all", lambda: self.tick_all(True)),
                              ("Untick all", lambda: self.tick_all(False))):
                if text is None:
                    ttk.Separator(side).pack(fill="x", pady=8)
                else:
                    ttk.Button(side, text=text, command=cmd, width=22).pack(pady=2)
            ttk.Label(side, text="Click the box (or press\nSpace) to tick a table.\n"
                                 "Ctrl+Up / Ctrl+Down\nalso move a table.",
                      foreground="#555").pack(pady=10)

            form = ttk.LabelFrame(self, text="Document")
            form.pack(fill="x", **pad)
            for r, (label, var) in enumerate((("Study", self.var_study),
                                              ("Report title", self.var_title),
                                              ("Save as", self.var_out))):
                ttk.Label(form, text=label + ":").grid(row=r, column=0, sticky="w",
                                                       padx=6, pady=3)
                ttk.Entry(form, textvariable=var).grid(row=r, column=1, sticky="we",
                                                       padx=6, pady=3)
            ttk.Button(form, text="Choose\u2026", command=self.choose_out).grid(
                row=2, column=2, padx=6)
            form.columnconfigure(1, weight=1)

            bottom = ttk.Frame(self)
            bottom.pack(fill="x", **pad)
            style = ttk.Style(self)
            style.configure("Big.TButton", font=("Segoe UI", 12, "bold"), padding=8)
            self.btn = ttk.Button(bottom, text="COMBINE", style="Big.TButton",
                                  command=self.combine)
            self.btn.pack(side="left")
            ttk.Label(bottom, textvariable=self.var_status).pack(side="left", padx=12)

            logf = ttk.Frame(self)
            logf.pack(fill="both", expand=False, **pad)
            self.txt = tk.Text(logf, height=9, wrap="none", font=("Consolas", 9),
                               state="disabled")
            lsb = ttk.Scrollbar(logf, orient="vertical", command=self.txt.yview)
            self.txt.configure(yscrollcommand=lsb.set)
            self.txt.pack(side="left", fill="both", expand=True)
            lsb.pack(side="left", fill="y")

        # ---- list handling
        def refresh(self):
            folder = Path(self.var_folder.get().strip() or ".")
            if not folder.is_dir():
                self.items = []
                self.var_status.set(f"Folder not found: {folder}")
            else:
                self.items = scan_folder(folder)
                self.var_status.set(f"{len(self.items)} RTF file(s) found")
            self._render()

        def _render(self, select: int | None = None):
            self.tree.delete(*self.tree.get_children())
            for n, it in enumerate(self.items):
                self.tree.insert("", "end", iid=str(n), values=(
                    TICK if it.include else NOTICK, it.label if it.number else "",
                    it.title + (f"  [unreadable: {it.error}]" if it.error else ""),
                    it.layout, it.path.name))
            if select is not None and 0 <= select < len(self.items):
                self.tree.selection_set(str(select))
                self.tree.focus(str(select))
                self.tree.see(str(select))

        def _selected(self):
            sel = self.tree.selection()
            return int(sel[0]) if sel else None

        def _on_click(self, event):
            if self.tree.identify_region(event.x, event.y) == "cell" and \
                    self.tree.identify_column(event.x) == "#1":
                row = self.tree.identify_row(event.y)
                if row:
                    self.items[int(row)].include ^= True
                    self._render(int(row))
                    return "break"

        def toggle_selected(self):
            i = self._selected()
            if i is not None:
                self.items[i].include ^= True
                self._render(i)

        def tick_all(self, value):
            for it in self.items:
                it.include = value
            self._render(self._selected())

        def move(self, step):
            i = self._selected()
            if i is None:
                return
            j = i + step
            if 0 <= j < len(self.items):
                self.items[i], self.items[j] = self.items[j], self.items[i]
                self._render(j)

        def sort_items(self):
            self.items.sort(key=TableInfo.sort_key)
            self._render()

        def browse(self):
            d = filedialog.askdirectory(initialdir=self.var_folder.get() or str(APP_DIR))
            if d:
                self.var_folder.set(d)
                self.refresh()

        def choose_out(self):
            cur = Path(self.var_out.get() or default_output(self.var_study.get()))
            f = filedialog.asksaveasfilename(
                initialdir=str(cur.parent), initialfile=cur.name,
                defaultextension=".docx", filetypes=[("Word document", "*.docx")])
            if f:
                self.var_out.set(f)

        # ---- combine
        def _log(self, line):
            self.txt.configure(state="normal")
            self.txt.insert("end", line + "\n")
            self.txt.see("end")
            self.txt.configure(state="disabled")

        def combine(self):
            if self.busy:
                return
            chosen = [it for it in self.items if it.include]
            if not chosen:
                messagebox.showwarning("Nothing to combine", "Tick at least one table.")
                return
            out = self.var_out.get().strip() or default_output(self.var_study.get())
            if not out.lower().endswith(".docx"):
                out += ".docx"
            self.var_out.set(out)
            self.settings.update(folder=self.var_folder.get(), study=self.var_study.get(),
                                 title=self.var_title.get(), output=out)
            save_settings(self.settings)
            self.busy = True
            self.btn.state(["disabled"])
            self.var_status.set(f"Combining {len(chosen)} table(s) in Word\u2026")
            self.txt.configure(state="normal")
            self.txt.delete("1.0", "end")
            self.txt.configure(state="disabled")
            items = list(self.items)   # snapshot of order and ticks
            study, title = self.var_study.get(), self.var_title.get()   # tk is main-thread only

            def work():
                try:
                    res = run_combine(items, study, title,
                                      out, emit=lambda s: self.q.put(("log", s)))
                    self.q.put(("done", res[:2] + (res[2].total_pages,)))
                except Exception as exc:
                    self.q.put(("log", f"ERROR: {exc}"))
                    self.q.put(("done", (False, None, 0)))

            threading.Thread(target=work, daemon=True).start()

        def _poll(self):
            try:
                while True:
                    kind, payload = self.q.get_nowait()
                    if kind == "log":
                        self._log(payload)
                    else:
                        self._finished(*payload)
            except queue.Empty:
                pass
            self.after(150, self._poll)

        def _finished(self, ok, log_path, pages):
            self.busy = False
            self.btn.state(["!disabled"])
            out = self.var_out.get()
            if ok:
                self.var_status.set(f"Done: {pages} pages, all checks passed")
                if messagebox.askyesno("Finished",
                                       f"Created {Path(out).name} ({pages} pages).\n"
                                       f"All page-count checks passed.\n\n"
                                       f"Run log: {log_path.name if log_path else '-'}\n\n"
                                       f"Open the document now?"):
                    os.startfile(out)
            else:
                self.var_status.set("Finished with problems - see the log")
                messagebox.showerror("Problem",
                                     "The combine did not pass all checks or failed.\n"
                                     f"See the log below"
                                     + (f" and {log_path}" if log_path else "") + ".")

    App().mainloop()


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Combine RTF tables into one Word document.")
    ap.add_argument("--run", action="store_true",
                    help="combine without opening the window")
    ap.add_argument("--folder", help="folder holding the RTF files")
    ap.add_argument("--files", nargs="*",
                    help="file names to include, in this order (default: all, by table number)")
    ap.add_argument("--study")
    ap.add_argument("--title")
    ap.add_argument("--out", help="output .docx (default <study>_tables.docx next to combine.py)")
    a = ap.parse_args(argv)
    if not a.run:
        run_gui()
        return 0
    s = load_settings()
    folder = Path(a.folder or s["folder"]).resolve()
    study = a.study or s["study"]
    title = a.title or s["title"]
    items = scan_folder(folder)
    if a.files:
        by_name = {i.path.name.lower(): i for i in items}
        missing = [f for f in a.files if f.lower() not in by_name]
        if missing:
            print("Not found in folder:", ", ".join(missing))
            return 2
        items = [by_name[f.lower()] for f in a.files]
    out = a.out or default_output(study)
    ok, log_path, _ = run_combine(items, study, title, out)
    print(f"\nLog written to {log_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # pythonw has no console: leave a note and show a message box
        err = traceback.format_exc()
        (APP_DIR / "combine_error.txt").write_text(err, encoding="utf-8")
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("RTF combiner", err[-1500:])
        except Exception:
            print(err)
        sys.exit(1)
