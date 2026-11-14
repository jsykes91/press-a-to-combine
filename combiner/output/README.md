# RTF table combiner

Puts RTF tables (for example from R `tfrmt`/`gt`) into one Word document, with a
title page, a clickable contents page, and page numbers you can trust.

## How to use it

1. Double-click **combine.bat**.
   The first time, it sets up its own copy of Python in a `.venv` folder next to it
   and downloads `pywin32` (needs internet once, takes about a minute). After that
   it opens the window straight away.
2. Pick the folder with the RTF files (it starts on `..\input`).
   Every `.rtf` is listed with its table number, title and page layout, sorted by
   table number.
3. Click the box in the **Include** column (or press Space) to leave a table out.
   Use **Move up / Move down** (or Ctrl+Up / Ctrl+Down) to change the order.
4. Check the study, report title and file name, then press **COMBINE**.

Word runs hidden in the background (usually under a minute). It doesn't affect any
Word windows you already have open. When it finishes you get a message saying
whether every check passed, and you can open the document.

## What you get

| Part | Details |
|---|---|
| Title page | Study, report title, today's date, list of the tables included |
| Contents page | One line per table. The text and the page number are links (Ctrl+Click in Word) |
| Tables | Each in its own section, with its own paper size, orientation, margins, titles, column headers and footnotes |
| "Page X of Y" at the top right | Unchanged: it still counts the table's own pages (e.g. Page 3 of 13) |
| "Overall Page X of Y" at the bottom right | Counts the whole document |
| Run log | `<name>_log.txt` next to the document: inputs (with MD5 checksums), steps, checks, PASS/FAIL |

## The checks (in every run log)

For each table:

- the number of pages matches the same RTF opened on its own in Word
- it starts on a new page straight after the previous table
- its orientation is kept
- its "Page X of Y" fields were found and converted

For the whole document: total pages = title and contents pages + all table pages.

If any check fails, the result says **CHECK FAILED** and names the table.

## Command line (optional)

```bat
combine.bat --run --folder ..\input --study CDISCPILOT01 --title "Section 14 Summary Tables"
combine.bat --run --folder ..\input --files t14-3-1-1-teae-summ.rtf t14-1-1-demog.rtf --out C:\temp\two_tables.docx
```

Without `--files` it takes every RTF in the folder, in table-number order.

## Good to know

- Needs Windows with Microsoft Word installed.
- The input RTFs are never changed. They are copied to a temporary folder and
  Word opens the copies, so Word doesn't even create lock files in the input folder.
- The window remembers your last folder, study, title and file name in
  `combine_settings.json`.
- Re-running overwrites the document and its log. Close the document in Word first.
- Word keeps the page numbers up to date if you edit the document. To refresh the
  contents page after edits, select all and press F9.
- How "Page X of Y" stays per table: in each table's header, `PAGE` becomes
  `{ = {PAGE} - {PAGEREF table_start} + 1 }` and `NUMPAGES` becomes
  `{ = {PAGEREF table_end} - {PAGEREF table_start} + 1 }`. Bookmarks such as
  `T_14_1_1` and `T_14_1_1_end` mark where each table starts and ends.
