#==============================================================================
# Study        : CDISCPILOT01 (CDISC SDTM/ADaM Pilot Project)
# Program      : common.R
# Output       : None (shared functions, sourced by each table program)
# Title        : Shared steps for the three ARS-driven tables
#
# Purpose      : Keep the steps every table needs in one place, so they are
#                written once and behave the same in every table:
#                  - run the ARD programme siera wrote for an output
#                  - read titles and footnotes from the ARS file
#                  - number formats (n (%), Mean (SD) and so on)
#                  - independent checks (QC) against the ADaM data
#                  - write the RTF: A4, titles in the page header,
#                    footnotes in the page footer, "Page X of Y"
# Inputs       : ars/Common_Safety_Displays_cards.json (ARS metadata)
#                ard-programs/ARD_<output id>.R (written by siera)
#                adam/ADSL.csv (for the checks)
# Outputs      : None
# Packages     : dplyr, tidyr, tfrmt, gt, jsonlite, readr
#                (versions recorded in logs/run_all.log)
# Author       : James Sykes
# Date         : 14NOV2026
# Validation   : Not validated. Demonstration only, not for
#                regulatory use.
#
# Modification history
# Date       Author       Change
# ---------  -----------  ---------------------------------------------
# 14NOV2026  James Sykes  First version.
#==============================================================================

suppressPackageStartupMessages({
  library(dplyr)
  library(tidyr)
  library(tfrmt)
  library(gt)
})

# ---- Settings used by every table -------------------------------------------

ARS_FILE  <- "ars/Common_Safety_Displays_cards.json"  # the ARS metadata
OUT_DIR   <- "rtf"                                    # where the tables go
TRT_ORDER <- c("Placebo", "Xanomeline Low Dose", "Xanomeline High Dose")

# A line break inside a title or column heading. gt writes a normal "\n" into
# the RTF as it is, and RTF ignores it, so this character is used instead and
# turned into a real RTF line break when the file is tidied (see tidy_rtf).
LINE_BREAK <- " "

# ---- 1. Run siera's ARD programme for one output ----------------------------
# siera wrote one R programme per ARS output (01_make_ard_programs.R). Running
# it gives the Analysis Results Dataset (ARD): one result per row, each row
# tagged with the ARS analysis, method and grouping that produced it.

run_ard <- function(output_id) {
  programme <- file.path("ard-programs", paste0("ARD_", output_id, ".R"))
  if (!file.exists(programme)) {
    stop("ARD programme not found: ", programme, ". Run 01_make_ard_programs.R first.")
  }
  env <- new.env()
  # siera's programmes print package start-up messages; those are not needed
  suppressMessages(source(programme, local = env))
  ard <- env$ARD
  # "stat" is a list column holding the same number as "res", so drop it
  ard$stat <- NULL
  ard <- as_tibble(ard)

  # Check: every treatment in the ARD is one we expect, so none is lost later
  trts <- unique(na.omit(ard$group1_level))
  unexpected <- setdiff(trts[grepl("Placebo|Xanomeline", trts)], TRT_ORDER)
  if (length(unexpected)) {
    stop("Unexpected treatment(s) in the ARD: ", paste(unexpected, collapse = ", "))
  }

  message("ARD for ", output_id, ": ", nrow(ard), " results")
  ard
}

# ---- 2. Titles, footnotes and footer from the ARS display -------------------
# The ARS file holds the text of each table's titles and footnotes, so the
# table and its metadata always agree. Some text is shared between tables
# ("global" sections) and is looked up by its id.

ars_display <- function(output_id, programme) {
  ars <- jsonlite::read_json(ARS_FILE)

  # All shared text, by id. [[ ]] is used rather than $ throughout, because
  # $ would also match the start of a longer name (subSection / subSectionId).
  texts <- list()
  for (s in ars[["globalDisplaySections"]]) {
    for (x in s[["subSections"]]) texts[[x[["id"]]]] <- x[["text"]]
  }

  # This output's own display, and any text defined in it
  output <- Filter(function(o) o[["id"]] == output_id, ars[["outputs"]])
  if (length(output) != 1) stop("Output ", output_id, " not found once in ", ARS_FILE)
  output <- output[[1]]
  sections <- output[["displays"]][[1]][["display"]][["displaySections"]]
  for (s in sections) {
    for (x in s[["orderedSubSections"]]) {
      if (!is.null(x[["subSection"]])) texts[[x[["subSection"]][["id"]]]] <- x[["subSection"]][["text"]]
    }
  }

  # The text lines of one section type (Title, Footnote...), in ARS order
  get_section <- function(type) {
    s <- Filter(function(x) x[["sectionType"]] == type, sections)
    if (!length(s)) return(character())
    subs <- s[[1]][["orderedSubSections"]]
    subs <- subs[order(vapply(subs, function(x) x[["order"]], numeric(1)))]
    vapply(subs, function(x) {
      if (!is.null(x[["subSection"]])) x[["subSection"]][["text"]] else texts[[x[["subSectionId"]]]]
    }, character(1))
  }

  # The RTF file name ARS gives for this output
  specs <- Filter(function(f) f[["fileType"]][["controlledTerm"]] == "rtf",
                  output[["fileSpecifications"]])
  file <- if (length(specs)) sub("^\\./", "", specs[[1]][["location"]]) else paste0(output_id, ".rtf")

  # The example's title holds placeholders ("Table 14.3.1.<x>.<y>"), so the
  # table number is taken from the output id instead (Out14-1-1 -> 14.1.1)
  titles <- get_section("Title")
  titles[1] <- paste("Table", gsub("-", ".", sub("^Out", "", output_id)))

  # Fill the footer placeholders: programme, output file and run date and time
  stamp <- toupper(format(Sys.time(), "%d%b%Y:%H:%M"))
  footer <- get_section("Footer")
  footer <- gsub("<pid><oid>.rtf", file, footer, fixed = TRUE)
  footer <- gsub("<pid>.sas", programme, footer, fixed = TRUE)
  footer <- gsub("DDMONYYYY:HH:MM", stamp, footer, fixed = TRUE)

  list(
    titles    = titles,
    notes     = c(get_section("Abbreviation"), get_section("Legend"), get_section("Footnote")),
    footer    = footer,
    row_label = trimws(get_section("Rowlabel Header")),
    file      = file
  )
}

# ---- 3. Big N: number of subjects per treatment ------------------------------
# Shown in the column headings as "(N=xx)". Taken from the ARD's safety
# population count, laid out the way tfrmt expects.

big_n_rows <- function(ard) {
  ard |>
    filter(AnalysisId == "An01_05_SAF_Summ_ByTrt") |>
    transmute(column = variable_level, param = "bigN", value = res)
}

# The tfrmt rule that prints big N on its own line under each treatment name
big_n_format <- big_n_structure(param_val = "bigN",
                                n_frmt = frmt(paste0(LINE_BREAK, "(N=xx)")))

# ---- 4. Number formats --------------------------------------------------------

# Continuous summaries: which statistic goes on which row, and in what order
cont_labels <- c(N = "n", mean = "Mean (SD)", sd = "Mean (SD)", median = "Median",
                 p25 = "Q1, Q3", p75 = "Q1, Q3", min = "Min, Max", max = "Min, Max")
cont_order  <- c(N = 1, mean = 2, sd = 2, median = 3, p25 = 4, p75 = 4, min = 5, max = 5)

# Continuous summaries: decimal places. Mean, median and quartiles get one
# more decimal than the data and the SD two more; min and max as recorded.
cont_formats <- function(group_spec = ".default") {
  list(
    frmt_structure(group_val = group_spec, label_val = "n", frmt("xxx")),
    frmt_structure(group_val = group_spec, label_val = "Mean (SD)",
                   frmt_combine("{mean} ({sd})", mean = frmt("xxx.x"), sd = frmt("xx.xx"))),
    frmt_structure(group_val = group_spec, label_val = "Median", frmt("xxx.x")),
    frmt_structure(group_val = group_spec, label_val = "Q1, Q3",
                   frmt_combine("{p25}, {p75}", p25 = frmt("xxx.x"), p75 = frmt("xxx.x"))),
    frmt_structure(group_val = group_spec, label_val = "Min, Max",
                   frmt_combine("{min}, {max}", min = frmt("xxx"), max = frmt("xxx")))
  )
}

# Counts: "n (xx.x%)". A count of 0 shows just "0", padded with spaces that
# Word can't drop (non-breaking), so it lines up under the other counts.
n_pct_format <- frmt_combine(
  "{n} {p}",
  n = frmt("xx"),
  p = frmt_when("==100" ~ frmt("(100%)"),
                "==0"   ~ strrep(" ", 7),
                TRUE    ~ frmt("(xx.x%)"))
)

# ---- 5. Independent checks (QC) ----------------------------------------------
# Each table re-calculates a few of its key numbers straight from the ADaM
# data, without siera or cards, and stops if they don't match the ARD. The
# result of every check is written to the run log.

qc_check <- function(what, expected, actual, tolerance = 1e-8) {
  expected <- as.numeric(expected)
  actual <- as.numeric(actual)
  ok <- length(expected) == length(actual) && all(abs(expected - actual) <= tolerance)
  if (!ok) {
    stop("QC check failed: ", what,
         "\n  expected (ADaM): ", paste(signif(expected, 6), collapse = ", "),
         "\n  table (ARD):     ", paste(signif(actual, 6), collapse = ", "))
  }
  message("QC check passed: ", what)
  invisible(TRUE)
}

# The safety population, straight from ADSL
read_safety_pop <- function() {
  readr::read_csv("adam/ADSL.csv", show_col_types = FALSE) |>
    filter(SAFFL == "Y")
}

# Big N in the ARD agrees with a direct count of the safety population
check_big_n <- function(ard) {
  expected <- read_safety_pop() |> count(TRT01A) |> arrange(match(TRT01A, TRT_ORDER))
  actual <- big_n_rows(ard) |> arrange(match(column, TRT_ORDER))
  qc_check("big N per treatment matches ADSL (safety population)",
           expected$n, actual$value)
}

# ---- 6. Write the RTF -----------------------------------------------------------
# Titles go in the page header and footnotes in the page footer, so both repeat
# on every page. gt adds the "Page X of Y" fields. Paper is A4, 1-inch margins.
#
# widths: the share of the table width (in %) for the row labels ("stub"), each
# treatment column ("column"), and the p-value column if there is one.

save_rtf <- function(gt_tbl, display, orientation = c("portrait", "landscape"),
                     widths = list(stub = 30, column = 20, pvalue = 10)) {
  orientation <- match.arg(orientation)
  dir.create(OUT_DIR, showWarnings = FALSE)

  # Titles from ARS: the table number, then each other title on its own line
  tbl <- gt_tbl |>
    tab_header(title = display$titles[1],
               subtitle = paste(display$titles[-1], collapse = LINE_BREAK))

  # Footnotes from ARS, then the footer lines (source, programme, run time)
  for (note in c(display$notes, display$footer)) tbl <- tab_source_note(tbl, note)

  # Treatments in the planned order, p-value last, row label heading from ARS
  tbl <- tbl |>
    cols_move_to_end(c(starts_with("Placebo"), starts_with("Xanomeline Low"),
                       starts_with("Xanomeline High"), any_of("p-value"))) |>
    tab_stubhead(label = paste(display$row_label, collapse = " / "))

  # Column widths, so the row labels have room and don't wrap mid-word.
  # gt only applies a width to the row label column ("stub") when it is named
  # directly, so the columns are named from gt's own list of them.
  columns <- tbl[["_boxhead"]]
  stub_col <- columns$var[columns$type == "stub"]
  value_cols <- setdiff(columns$var[columns$type == "default"], "p-value")
  width_rules <- list(
    rlang::new_formula(rlang::sym(stub_col), pct(widths$stub)),
    rlang::new_formula(rlang::call2("all_of", value_cols), pct(widths$column))
  )
  if ("p-value" %in% columns$var) {
    width_rules <- c(width_rules,
                     rlang::new_formula(rlang::sym("p-value"), pct(widths$pvalue)))
  }
  tbl <- do.call(cols_width, c(list(tbl), width_rules))

  # Page set-up. gt expects the portrait size and turns it round for landscape.
  tbl <- tbl |>
    tab_options(
      table.font.names = "Courier New",
      table.font.size = px(12),
      page.orientation = orientation,
      page.numbering = TRUE,
      page.header.use_tbl_headings = TRUE,
      page.footer.use_tbl_notes = TRUE,
      page.width = "8.27in", page.height = "11.69in",
      page.margin.left = "1in", page.margin.right = "1in",
      page.margin.top = "1in", page.margin.bottom = "1in"
    )

  path <- file.path(OUT_DIR, display$file)
  gtsave(tbl, path)
  tidy_rtf(path, orientation)
  message("Wrote ", path)
  invisible(path)
}

# ---- 7. Tidy the RTF that gt wrote ------------------------------------------
# gt 1.4.0 writes a few things Word misreads. Each one is fixed here, then the
# file is checked, so a change in a future gt version is noticed.
#   a) Paper size with decimals (\paperw11908.8). RTF sizes must be whole
#      numbers: Word printed the ".8" and ".6" as text at the top of the table.
#   b) "Landscape" (\lndscpsxn) is set even for portrait tables.
#   c) Our line-break character becomes an RTF line break (\line).
#   d) Characters outside basic ASCII (non-breaking spaces, "≥") are written as
#      raw UTF-8, which Word reads as "Â" and other symbols. RTF needs them as
#      \u codes.
#   e) Spelling and grammar checks are switched off for the table text
#      (\noproof), so Word doesn't underline drug names and numbers.

tidy_rtf <- function(path, orientation) {
  rtf <- readLines(path, warn = FALSE, encoding = "UTF-8")

  # a) Whole-number A4 paper size, in twips (1/1440 of an inch)
  rtf <- sub("\\\\paperw[0-9.]+\\\\paperh[0-9.]+",
             if (orientation == "portrait") "\\\\paperw11906\\\\paperh16838"
             else "\\\\paperw16838\\\\paperh11906",
             rtf)

  # b) Portrait tables: remove the landscape setting
  if (orientation == "portrait") rtf <- gsub("\\lndscpsxn", "", rtf, fixed = TRUE)

  # c) Line breaks (before d, which would otherwise encode them). gt writes
  #    some characters as RTF codes itself, so look for its code (\u8232) too.
  rtf <- gsub(LINE_BREAK, "\\line ", rtf, fixed = TRUE)
  rtf <- gsub("\\\\u8232 ?", "\\\\line ", rtf)

  # d) Every other non-ASCII character as an RTF unicode code: {\uc1\uNNNN?}
  has_unicode <- grepl("[^\\x01-\\x7F]", rtf, perl = TRUE)
  rtf[has_unicode] <- vapply(rtf[has_unicode], function(line) {
    codes <- utf8ToInt(enc2utf8(line))
    chars <- vapply(codes, function(code) {
      if (code < 128) intToUtf8(code)
      else sprintf("{\\uc1\\u%d?}", if (code > 32767) code - 65536 else code)
    }, character(1))
    paste(chars, collapse = "")
  }, character(1), USE.NAMES = FALSE)

  # e) No spelling or grammar marks on the table text
  rtf <- gsub("\\f0\\fs20 ", "\\f0\\fs20\\noproof ", rtf, fixed = TRUE)

  writeLines(rtf, path, useBytes = TRUE)

  # Check the fixes held
  rtf <- readLines(path, warn = FALSE)
  problems <- c(
    if (!any(grepl("\\\\paperw[0-9]+\\\\paperh[0-9]+\\\\", rtf))) "paper size not whole numbers",
    if (orientation == "portrait" && any(grepl("\\lndscpsxn", rtf, fixed = TRUE))) "portrait table marked landscape",
    if (any(grepl("[^\\x01-\\x7F]", rtf, perl = TRUE))) "non-ASCII characters left in the RTF",
    if (any(grepl("\\u8232", rtf, fixed = TRUE))) "line-break character left in the RTF"
  )
  if (length(problems)) stop("RTF tidy-up failed for ", path, ": ", paste(problems, collapse = "; "))
  invisible(path)
}
