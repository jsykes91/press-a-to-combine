# ARS to RTF: three CDISC pilot tables in R

Three tables from the CDISC pilot study (CDISCPILOT01), made from ARS metadata:

```
ARS file  --siera-->  ARD programmes  --cards-->  ARDs  --tfrmt + gt-->  RTF tables
```

| Table | Programme | Layout |
| --- | --- | --- |
| 14.1.1 Summary of Demographics | `t14-1-1-demog.R` | landscape, 2 pages |
| 14.3.1.1 Overall Summary of TEAEs | `t14-3-1-1-teae.R` | landscape, 1 page |
| 14.3.3.1a Vital Signs, Observed and Change from Baseline | `t14-3-3-1-vitals.R` | landscape, 13 pages |

## Run it

You need R (4.4 or later; tested with 4.6.0) and, ideally, RStudio.

1. Download the repository (green **Code** button > **Download ZIP**) and unzip it.
2. In RStudio, open `r/run_all.R`, then **Session > Set Working Directory > To Source File
   Location**. The programs read and write files relative to this folder.
3. Once: in the Console, `source("00_install_packages.R")`. This installs the packages,
   including the GitHub version of siera (ready-built, from R-universe: no Rtools needed).
4. Each time: `source("run_all.R")`. It says "Done" when it finishes. The tables appear in
   `rtf/` and the run log in `logs/run_all.log`. If anything fails, including a check,
   it stops and the log says why.

The log records the date, R and package versions, an MD5 fingerprint of every input
file, the result of every check, and any warning or error.

## Checks built in

Each table programme recalculates key numbers straight from the ADaM data, without
siera or cards, and stops if they disagree with the ARD:

| Table | Checked against ADaM |
| --- | --- |
| All three | Big N per treatment (ADSL safety population) |
| 14.1.1 | Mean age, number of women per treatment (ADSL) |
| 14.3.1.1 | Subjects with any TEAE per treatment (ADAE) |
| 14.3.3.1a | Systolic BP baseline n and mean per treatment (ADVS) |

Every programme has a standard header (study, inputs, outputs, purpose, history).
The programmes in `ard-programs/` are written by siera and are not edited by hand.

## What's in here

| Folder or file | What |
| --- | --- |
| `ars/` | The ARS metadata: CDISC's Common Safety Displays example, as adapted for siera (the JSON is used; the Excel workbook is the same metadata in siera's spreadsheet form) |
| `adam/` | CDISC pilot ADaM data as CSV: ADSL, ADAE, ADVS |
| `01_make_ard_programs.R` | siera reads the ARS file and writes one R programme per output into `ard-programs/` |
| `ard-programs/` | The programmes siera wrote. Each one makes an ARD (one result per row) |
| `common.R` | Shared steps: run an ARD programme, read titles and footnotes from ARS, save the RTF |
| `t14-*.R` | One programme per table: ARD to tfrmt to RTF |
| `run_all.R` | Runs everything in order and writes the log |
| `logs/` | The run log |

The RTFs have titles and "Page X of Y" in the page header, and footnotes in the page footer.

## Where the files came from

- `ars/Common_Safety_Displays_cards.json`: CDISC's Common Safety Displays ARS example, as
  adapted for and supplied with the [siera](https://github.com/clymbclinical/siera)
  package (Clymb Clinical, MIT licence).
- `adam/ADSL.csv`, `adam/ADAE.csv`, `adam/ADVS.csv`: the CDISC pilot study (CDISCPILOT01)
  ADaM datasets from [phuse-org/phuse-scripts](https://github.com/phuse-org/phuse-scripts)
  (`data/adam/cdisc/`, MIT licence). Converted from SAS transport files (.xpt) to CSV with
  `haven::read_xpt()` and `readr::write_csv()`, with variable labels and formats dropped
  and no values changed.

## Worth knowing

- siera is the GitHub version (commit 9208a9b or later), installed from R-universe: the
  CRAN release can't fully read this JSON file.
- gt 1.4.0 writes a few things Word misreads, so `common.R` tidies each RTF after gt
  writes it (and checks the result): paper sizes with decimals (Word printed ".8.6" at
  the top of the table), "landscape" set on portrait tables, raw UTF-8 characters (shown
  in Word as "Â") and line breaks RTF ignores.
- The vital signs n counts readings, not subjects: each subject has three readings per
  visit (lying, standing 1 minute, standing 3 minutes).
- The original 2006 CDISC pilot study report, with its tables, is in CDISC's
  [SDTM/ADaM pilot project](https://github.com/cdisc-org/sdtm-adam-pilot-project)
  repository. Its table numbers differ: demographics is 14-2.01, adverse events 14-5.01,
  vital signs 14-7.01 and 14-7.02.
- CDISC's own example results file (in the ARS GitHub repository) shows Low and High Dose
  swapped for ethnicity, race and height. These tables are calculated from the ADaM data,
  and a direct count of ADSL agrees with them.
