#==============================================================================
# Study        : CDISCPILOT01 (CDISC SDTM/ADaM Pilot Project)
# Program      : t14-1-1-demog.R
# Output       : rtf/t14-1-1-demog.rtf
# Title        : Table 14.1.1 Summary of Demographics
#                Safety Population
# ARS output   : Out14-1-1
#
# Purpose      : Create the demographics table from ARS metadata:
#                ARS -> siera ARD programme -> tfrmt layout -> gt -> RTF.
# Inputs       : ars/Common_Safety_Displays_cards.json (ARS metadata)
#                ard-programs/ARD_Out14-1-1.R (written by siera)
#                adam/ADSL.csv
#                common.R (shared functions)
# Outputs      : rtf/t14-1-1-demog.rtf (landscape)
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
# The ARD holds every number in the table; ARS holds its titles and footnotes.

ard     <- run_ard("Out14-1-1")
display <- ars_display("Out14-1-1", programme = "t14-1-1-demog.R")

# ---- Step 2: Independent checks against ADSL ----------------------------------

check_big_n(ard)

adsl <- read_safety_pop()
expected_age <- adsl |> group_by(TRT01A) |> summarise(mean = mean(AGE)) |>
  arrange(match(TRT01A, TRT_ORDER))
actual_age <- ard |> filter(AnalysisId == "An03_01_Age_Summ_ByTrt", stat_name == "mean") |>
  arrange(match(group1_level, TRT_ORDER))
qc_check("mean age per treatment matches ADSL", expected_age$mean, actual_age$res)

expected_female <- adsl |> group_by(TRT01A) |> summarise(n = sum(SEX == "F")) |>
  arrange(match(TRT01A, TRT_ORDER))
actual_female <- ard |>
  filter(AnalysisId == "An03_03_Sex_Summ_ByTrt", stat_name == "n", group2_level == "Female") |>
  arrange(match(group1_level, TRT_ORDER))
qc_check("number of women per treatment matches ADSL", expected_female$n, actual_female$res)

# ---- Step 3: The rows of the table, in order ------------------------------------
# Each block is one characteristic: its summary analysis, its comparison
# analysis (the p-value), the heading shown, and whether it is continuous
# (n, mean, ...) or categorical (n (%)). Analysis ids are those in the ARS file.

blocks <- tribble(
  ~summ,                        ~comp,                        ~group,         ~type,
  "An03_01_Age_Summ_ByTrt",    "An03_01_Age_Comp_ByTrt",    "Age (years)",  "cont",
  "An03_02_AgeGrp_Summ_ByTrt", "An03_02_AgeGrp_Comp_ByTrt", "Age group",    "cat",
  "An03_03_Sex_Summ_ByTrt",    "An03_03_Sex_Comp_ByTrt",    "Sex",          "cat",
  "An03_04_Ethnic_Summ_ByTrt", "An03_04_Ethnic_Comp_ByTrt", "Ethnicity",    "cat",
  "An03_05_Race_Summ_ByTrt",   "An03_05_Race_Comp_ByTrt",   "Race",         "cat",
  "An03_06_Height_Summ_ByTrt", "An03_06_Height_Comp_ByTrt", "Height (cm)",  "cont"
) |>
  mutate(ord1 = row_number())

# ---- Step 4: Reshape the ARD into tfrmt's layout -------------------------------
# tfrmt wants one row per number: group, label, column, statistic, value,
# plus sort keys. Category order comes from the ARS grouping (its id ends in
# the order number). Percentages are stored as 0-1 in the ARD, so x 100.

body <- bind_rows(lapply(seq_len(nrow(blocks)), function(i) {
  b <- blocks[i, ]
  rows <- ard |> filter(AnalysisId == b$summ)
  if (nrow(rows) == 0) stop("No results in the ARD for ", b$summ)

  if (b$type == "cont") {
    rows <- rows |>
      transmute(label = cont_labels[stat_name], ord2 = cont_order[stat_name],
                column = group1_level, param = stat_name, value = res)
  } else {
    rows <- rows |>
      mutate(ord2 = as.numeric(sub(".*_", "", group2_groupId))) |>
      transmute(label = group2_level, ord2, column = group1_level, param = stat_name,
                value = if_else(stat_name == "p", res * 100, res))
  }

  # The p-value goes on the first row of each block, in its own column
  first <- rows |> arrange(ord2) |> slice(1)
  pval <- ard |>
    filter(AnalysisId == b$comp) |>
    transmute(label = first$label, ord2 = first$ord2, column = "p-value",
              param = "pval", value = res)
  if (nrow(pval) != 1) stop("Expected one p-value for ", b$comp, ", found ", nrow(pval))

  bind_rows(rows, pval) |> mutate(group = b$group, ord1 = b$ord1)
}))

table_data <- bind_rows(body, big_n_rows(ard))

# ---- Step 5: Lay out and format the table with tfrmt ---------------------------
# Continuous blocks use the shared n / Mean (SD) / ... formats; categorical
# blocks use n (%); p-values have 4 decimals. Group headings sit above their
# rows, with the rows indented beneath them.

demog_tfrmt <- tfrmt(
  group = group,
  label = label,
  column = column,
  param = param,
  value = value,
  sorting_cols = c(ord1, ord2),
  body_plan = do.call(body_plan, c(
    cont_formats(list(group = c("Age (years)", "Height (cm)"))),
    list(
      frmt_structure(group_val = list(group = c("Age group", "Sex", "Ethnicity", "Race")),
                     label_val = ".default", n_pct_format),
      frmt_structure(group_val = ".default", label_val = ".default", pval = frmt("x.xxxx"))
    )
  )),
  big_n = big_n_format,
  col_plan = col_plan(group, label, all_of(TRT_ORDER), `p-value`, -ord1, -ord2),
  row_grp_plan = row_grp_plan(label_loc = element_row_grp_loc(location = "indented"))
)

demog_gt <- print_to_gt(demog_tfrmt, table_data)

# ---- Step 6: Write the RTF (landscape) -----------------------------------------

save_rtf(demog_gt, display, "landscape",
         widths = list(stub = 37, column = 18, pvalue = 9))
