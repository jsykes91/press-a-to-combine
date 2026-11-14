#==============================================================================
# Study        : CDISCPILOT01 (CDISC SDTM/ADaM Pilot Project)
# Program      : 01_make_ard_programs.R
# Output       : ard-programs/ARD_<output id>.R (one per ARS output)
# Title        : Write the ARD programmes from the ARS metadata
#
# Purpose      : siera reads the ARS file and writes one R programme per
#                output. Each programme reads the ADaM data in adam/ and makes
#                an Analysis Results Dataset (ARD): one result per row, linked
#                back to the ARS analysis that defined it. These programmes are
#                generated, so they are not edited by hand.
# Inputs       : ars/Common_Safety_Displays_cards.json (ARS metadata)
# Outputs      : ard-programs/ARD_Out14-1-1.R, ARD_Out14-3-1-1.R,
#                ARD_Out14-3-3-1a.R, ARD_Out14-3-3-1b.R
# Packages     : siera (GitHub version, see 00_install_packages.R)
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

library(siera)

# ---- Step 1: Write the programmes -------------------------------------------------
# Arguments, in order: the ARS file, the folder for the programmes, and the
# folder the programmes will read the ADaM data from. siera doesn't create the
# programmes folder itself, so it is made first (needed on a fresh download).

dir.create("ard-programs", showWarnings = FALSE)
readARS(
  "ars/Common_Safety_Displays_cards.json",
  "ard-programs",
  "adam"
)

# ---- Step 2: Check one programme was written for each output -------------------

expected <- paste0("ARD_", c("Out14-1-1", "Out14-3-1-1", "Out14-3-3-1a", "Out14-3-3-1b"), ".R")
missing <- setdiff(expected, list.files("ard-programs"))
if (length(missing)) stop("siera did not write: ", paste(missing, collapse = ", "))

message("ARD programmes written: ", paste(list.files("ard-programs"), collapse = ", "))
