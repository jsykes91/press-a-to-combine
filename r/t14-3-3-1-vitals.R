#==============================================================================
# Study        : CDISCPILOT01 (CDISC SDTM/ADaM Pilot Project)
# Program      : t14-3-3-1-vitals.R
# Output       : rtf/t14-3-3-1-vitals-chgbl.rtf
# Title        : Table 14.3.3.1a Summary of Observed and Change from
#                Baseline by Scheduled Visits - Vital Signs
#                Safety Population
# ARS output   : Out14-3-3-1a
#
# Purpose      : Create the vital signs table from ARS metadata:
#                ARS -> siera ARD programme -> tfrmt layout -> gt -> RTF.
# Inputs       : ars/Common_Safety_Displays_cards.json (ARS metadata)
#                ard-programs/ARD_Out14-3-3-1a.R (written by siera)
#                adam/ADSL.csv, adam/ADVS.csv
#                common.R (shared functions)
# Outputs      : rtf/t14-3-3-1-vitals-chgbl.rtf
# Packages     : siera, cards, cardx, tfrmt, gt, dplyr, tidyr, readr
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

ard     <- run_ard("Out14-3-3-1a")
display <- ars_display("Out14-3-3-1a", programme = "t14-3-3-1-vitals.R")

# Parameter names and visit order come from the ADaM data
advs <- readr::read_csv("adam/ADVS.csv", show_col_types = FALSE,
                        col_select = c(USUBJID, PARAMCD, PARAM, PARAMN, AVISIT, AVISITN,
                                       AVAL, ANL01FL))
params <- advs |> distinct(PARAMCD, PARAM, PARAMN)
visits <- advs |> filter(!is.na(AVISIT)) |> distinct(AVISIT, AVISITN)

# ---- Step 2: Independent checks against ADSL and ADVS -------------------------
# Systolic blood pressure at baseline: number of analysed records and their
# mean, by the treatment the subject actually received.

check_big_n(ard)

expected_sysbp <- advs |>
  filter(PARAMCD == "SYSBP", AVISIT == "Baseline", ANL01FL == "Y") |>
  inner_join(read_safety_pop() |> select(USUBJID, TRT01A), by = "USUBJID") |>
  group_by(TRT01A) |>
  summarise(n = n(), mean = mean(AVAL)) |>
  arrange(match(TRT01A, TRT_ORDER))
actual_sysbp <- ard |>
  filter(AnalysisId == "An08_01_Obs_Summ_ByTrt", group2_level == "SYSBP",
         group3_level == "Baseline") |>
  select(group1_level, stat_name, res) |>
  pivot_wider(names_from = stat_name, values_from = res) |>
  arrange(match(group1_level, TRT_ORDER))
qc_check("systolic BP baseline n per treatment matches ADVS", expected_sysbp$n, actual_sysbp$N)
qc_check("systolic BP baseline mean per treatment matches ADVS", expected_sysbp$mean, actual_sysbp$mean)

# Check: every parameter and visit in the ARD has a name and an order
unknown_param <- setdiff(unique(ard$group2_level[ard$AnalysisId == "An08_01_Obs_Summ_ByTrt"]), params$PARAMCD)
unknown_visit <- setdiff(unique(ard$group3_level[ard$AnalysisId == "An08_01_Obs_Summ_ByTrt"]), visits$AVISIT)
if (length(unknown_param) || length(unknown_visit)) {
  stop("ARD has parameters or visits not in ADVS: ", paste(c(unknown_param, unknown_visit), collapse = ", "))
}

# ---- Step 3: Reshape the ARD into tfrmt's layout -------------------------------
# Two ARS analyses: observed values (An08_01) and change from baseline
# (An08_02). Each treatment gets an "Observed" and a "Change" column; rows are
# grouped by parameter, then visit, then statistic.

body <- ard |>
  filter(AnalysisId %in% c("An08_01_Obs_Summ_ByTrt", "An08_02_ChgBl_Summ_ByTrt")) |>
  transmute(
    trt     = group1_level,
    type    = if_else(AnalysisId == "An08_01_Obs_Summ_ByTrt", "Observed", "Change"),
    PARAMCD = group2_level,
    AVISIT  = group3_level,
    label   = cont_labels[stat_name],
    ord3    = cont_order[stat_name],
    param   = stat_name,
    value   = res
  ) |>
  left_join(params, by = "PARAMCD") |>
  left_join(visits, by = "AVISIT") |>
  rename(parameter = PARAM, visit = AVISIT, ord1 = PARAMN, ord2 = AVISITN) |>
  select(-PARAMCD)

big_n <- big_n_rows(ard) |> rename(trt = column)

# ---- Step 4: Lay out and format the table with tfrmt ---------------------------
# Treatment names span their Observed and Change columns, with big N below.

vitals_tfrmt <- tfrmt(
  group = c(parameter, visit),
  label = label,
  column = c(trt, type),
  param = param,
  value = value,
  sorting_cols = c(ord1, ord2, ord3),
  body_plan = do.call(body_plan, cont_formats()),
  big_n = big_n_format,
  col_plan = col_plan(parameter, visit, label, everything(), -ord1, -ord2, -ord3),
  row_grp_plan = row_grp_plan(label_loc = element_row_grp_loc(location = "indented"))
)

vitals_gt <- print_to_gt(vitals_tfrmt, bind_rows(body, big_n))

# ---- Step 5: Write the RTF (landscape, several pages) --------------------------

save_rtf(vitals_gt, display, "landscape",
         widths = list(stub = 25, column = 12.5, pvalue = 0))
