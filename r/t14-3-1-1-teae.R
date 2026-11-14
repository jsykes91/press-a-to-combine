#==============================================================================
# Study        : CDISCPILOT01 (CDISC SDTM/ADaM Pilot Project)
# Program      : t14-3-1-1-teae.R
# Output       : rtf/t14-3-1-1-teae-summ.rtf
# Title        : Table 14.3.1.1 Overall Summary of Treatment-Emergent
#                Adverse Events
#                Safety Population
# ARS output   : Out14-3-1-1
#
# Purpose      : Create the overall adverse event summary from ARS metadata:
#                ARS -> siera ARD programme -> tfrmt layout -> gt -> RTF.
# Inputs       : ars/Common_Safety_Displays_cards.json (ARS metadata)
#                ard-programs/ARD_Out14-3-1-1.R (written by siera)
#                adam/ADSL.csv, adam/ADAE.csv
#                common.R (shared functions)
# Outputs      : rtf/t14-3-1-1-teae-summ.rtf
# Packages     : siera, cards, cardx, tfrmt, gt, dplyr, tidyr
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

source("common.R")

# ---- Step 1: Get the results and the display text -----------------------------

ard     <- run_ard("Out14-3-1-1")
display <- ars_display("Out14-3-1-1", programme = "t14-3-1-1-teae.R")

# ---- Step 2: Independent checks against ADSL and ADAE -------------------------
# Subjects with at least one TEAE: count each safety subject once, by the
# treatment they actually received (TRT01A in ADSL).

check_big_n(ard)

adsl <- read_safety_pop()
adae <- readr::read_csv("adam/ADAE.csv", show_col_types = FALSE)
expected_teae <- adae |>
  filter(TRTEMFL == "Y") |>
  distinct(USUBJID) |>
  inner_join(adsl |> select(USUBJID, TRT01A), by = "USUBJID") |>
  count(TRT01A) |>
  arrange(match(TRT01A, TRT_ORDER))
actual_teae <- ard |>
  filter(AnalysisId == "An07_01_TEAE_Summ_ByTrt", stat_name == "n") |>
  arrange(match(group1_level, TRT_ORDER))
qc_check("subjects with any TEAE per treatment match ADAE", expected_teae$n, actual_teae$res)

# ---- Step 3: The rows of the table, in order -----------------------------------
# One row per ARS analysis; labels as in the ARS list of contents.

rows <- tribble(
  ~AnalysisId,                          ~label,
  "An07_01_TEAE_Summ_ByTrt",           "TEAE",
  "An07_02_RelTEAE_Summ_ByTrt",        "Related TEAE",
  "An07_03_SerTEAE_Summ_ByTrt",        "Serious TEAE",
  "An07_04_RelSerTEAE_Summ_ByTrt",     "Related Serious TEAE",
  "An07_05_TEAELd2Dth_Summ_ByTrt",     "TEAE Leading to Death",
  "An07_06_RelTEAELd2Dth_Summ_ByTrt",  "Related TEAE Leading to Death",
  "An07_07_TEAELd2DoseMod_Summ_ByTrt", "TEAE Leading to Dose Modification [a]",
  "An07_08_TEAELd2TrtDsc_Summ_ByTrt",  "TEAE Leading to Treatment Discontinuation"
) |>
  mutate(ord1 = row_number())

# Check: every row's analysis exists in the ARS file's results for this output
missing <- setdiff(rows$AnalysisId, ard$AnalysisId)
if (length(missing)) message("Note: no subjects (so no ARD rows) for: ", paste(missing, collapse = ", "))

# ---- Step 4: Reshape the ARD into tfrmt's layout -------------------------------
# Every row needs a count for every treatment. A treatment with no events has
# no result in the ARD, so it is filled in as 0. Percentages x 100.

body <- rows |>
  tidyr::crossing(column = TRT_ORDER, param = c("n", "p")) |>
  left_join(ard |> transmute(AnalysisId, column = group1_level, param = stat_name, value = res),
            by = c("AnalysisId", "column", "param")) |>
  mutate(value = coalesce(if_else(param == "p", value * 100, value), 0),
         group = "Number of subjects with at least one:") |>
  select(group, label, column, param, value, ord1)

table_data <- bind_rows(body, big_n_rows(ard))

# ---- Step 5: Lay out and format the table with tfrmt ---------------------------
# All rows are n (%), under one group heading.

teae_tfrmt <- tfrmt(
  group = group,
  label = label,
  column = column,
  param = param,
  value = value,
  sorting_cols = c(ord1),
  body_plan = body_plan(
    frmt_structure(group_val = ".default", label_val = ".default", n_pct_format)
  ),
  big_n = big_n_format,
  col_plan = col_plan(group, label, everything(), -ord1),
  row_grp_plan = row_grp_plan(label_loc = element_row_grp_loc(location = "indented"))
)

teae_gt <- print_to_gt(teae_tfrmt, table_data)

# ---- Step 6: Write the RTF (landscape) -----------------------------------------

save_rtf(teae_gt, display, "landscape",
         widths = list(stub = 43, column = 19, pvalue = 0))
