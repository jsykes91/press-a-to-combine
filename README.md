# Press A(RS) to Combine

**From ARS metadata to one combined Word document.** The companion code to the STAT-BLOG
post [Press A(RS) to Combine](https://stat-blog.com/posts/press-a-to-combine/).

Two parts:

1. **`r/`**: three tables from the CDISC pilot study (CDISCPILOT01), made in R straight
   from CDISC Analysis Results Standard (ARS) metadata:
   ARS file → **siera** writes the R programs → **cards** calculates the results →
   **tfrmt** and **gt** write the RTF tables.
2. **`combiner/`**: a Python tool, built by Claude Code from one prompt, that combines RTF
   tables into one Word document: a title page, a clickable contents page, each table's
   own "Page X of Y" kept, and an overall "Page X of Y" for the whole document.

## What's here

```
r/                                 part 1: ARS metadata to RTF tables (see r/README.md)
├── 00_install_packages.R          run once
├── run_all.R                      runs everything, with a log and checks
├── 01_make_ard_programs.R         siera writes one R program per ARS output
├── common.R                       shared steps: titles, formats, checks, RTF
├── t14-1-1-demog.R                Table 14.1.1   Summary of Demographics
├── t14-3-1-1-teae.R               Table 14.3.1.1 Overall Summary of TEAEs
├── t14-3-3-1-vitals.R             Table 14.3.3.1a Vital Signs by Visit
├── ars/                           the ARS metadata
└── adam/                          CDISC pilot ADaM data (ADSL, ADAE, ADVS) as CSV
combiner/                          part 2: the RTF combiner
├── input/                         the three RTF tables made by r/
└── output/                        what Claude built from one prompt, untouched
    ├── combine.py                 the window and the Word engine
    ├── combine.bat                double-click to run (Windows)
    ├── README.md                  how it works, and every check it makes
    ├── CDISCPILOT01_tables.docx   the combined document (18 pages)
    └── CDISCPILOT01_tables_log.txt
```

## Try it

**Part 1, the tables (any computer with R):** install R (4.4 or later) and RStudio,
then follow [r/README.md](r/README.md): run `00_install_packages.R` once, then
`run_all.R`. The tables appear in `r/rtf/`.

**Part 2, the combiner (Windows with Microsoft Word):**

1. Install [Python](https://www.python.org/downloads/) 3.11 or newer (tick "Add
   python.exe to PATH").
2. Download this repository (green **Code** button > **Download ZIP**) and unzip it.
3. Double-click `combiner/output/combine.bat`. The first run sets up Python (it downloads
   pywin32 once), then the window opens with the tables in `combiner/input/` listed.
4. Tick the tables you want, put them in order, and press **COMBINE**.

Word runs hidden in the background. When it finishes, the document and its run log are
saved in `combiner/output/`.

## The prompt

Everything in `combiner/output/` was built by Claude Code from this one prompt (about 35
minutes), with the three RTF tables in `combiner/input/` as the starting point:

> You're an expert statistical programmer who loves Python. Build an RTF combiner in one
> go, without asking me questions; tell me at the end about any choices you made.
>
> In C:\Combine\input there are three tables from the CDISC pilot study, made in R with
> tfrmt and gt. Open them first to see how they're built: sections, headers, footers and
> page fields. Don't change anything in input.
>
> In C:\Combine\output, create:
> - combine.py: a simple window (tkinter) that lists every RTF in a chosen folder with its
>   table number and title, lets me tick which to include and change their order, and has
>   a COMBINE button
> - combine.bat, which sets up Python the first time and then opens the window
> - a short README, and a test run of all three tables: CDISCPILOT01_tables.docx with a
>   run log
>
> Use Word (through pywin32) to build the .docx. Start with a title page (study, report
> title, date, list of tables) and a contents page with clickable links and page numbers.
> Keep each table's own portrait or landscape layout.
>
> Each table must still say "Page X of Y" for its own pages, exactly as it did on its own.
> Add an overall "Page X of Y" for the whole document in the footer.
>
> Check the page counts against the inputs, then tell me what you checked.

## Worth knowing

- **The combiner is exactly what the one-shot produced.** I haven't edited it. The only
  file left out is `combine_settings.json`, where the window remembers your last folder.
- **The example document was built from the files in `combiner/input/`.** Their MD5
  fingerprints in the run log match. Running `r/` again makes the same tables, with a new
  date and time in each footer.
- **CDISC's example ARS results have two arms swapped.** The results stored in CDISC's own
  example file show Low and High Dose swapped for ethnicity, race and mean height. The
  tables here are calculated from the ADaM data, and they agree with a direct count of
  ADSL and with the original 2006 study report.
- **A demo, not a validated tool.** The R programs have checks against the data and the
  combiner checks its page counts, but "it passes its own checks" isn't the same as
  validated. Review everything before using it for real work.

## Where the data came from

- **ARS metadata** (`r/ars/`): CDISC's Common Safety Displays example
  ([cdisc-org/analysis-results-standard](https://github.com/cdisc-org/analysis-results-standard),
  MIT), as adapted for and supplied with
  [siera](https://github.com/clymbclinical/siera) (Clymb Clinical, MIT).
- **ADaM data** (`r/adam/`): the CDISC pilot study ADSL, ADAE and ADVS from
  [phuse-org/phuse-scripts](https://github.com/phuse-org/phuse-scripts) (MIT), converted
  from SAS transport files to CSV with no values changed.
- The original CDISC pilot study report is in CDISC's
  [SDTM/ADaM pilot project](https://github.com/cdisc-org/sdtm-adam-pilot-project).

## Licence

MIT. See [LICENSE](LICENSE). The ARS metadata and ADaM data keep their own MIT licences
(above).
