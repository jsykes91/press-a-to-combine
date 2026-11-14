#==============================================================================
# Study        : CDISCPILOT01 (CDISC SDTM/ADaM Pilot Project)
# Program      : 00_install_packages.R
# Output       : None (installs R packages)
# Title        : Install the R packages the pipeline needs
#
# Purpose      : Install, once, every package the programs use. siera comes
#                from its GitHub version, not CRAN: the CRAN release (0.5.6)
#                can't fully read the JSON example used here. It is installed
#                from R-universe, which builds the GitHub version ready to
#                install, so Windows doesn't need extra build tools (Rtools).
# Inputs       : None (downloads from CRAN and R-universe)
# Outputs      : None
# Packages     : dplyr, tidyr, readr, jsonlite, cards, cardx, broom,
#                broom.helpers, parameters, tfrmt, gt, siera
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

# ---- Step 1: Packages from CRAN ------------------------------------------------
# Only those not already installed. broom, broom.helpers and parameters are
# used by the ARD programmes siera writes (for the p-values).

pkgs <- c("dplyr", "tidyr", "readr", "jsonlite", "cards", "cardx", "broom",
          "broom.helpers", "parameters", "tfrmt", "gt")
missing <- setdiff(pkgs, rownames(installed.packages()))
if (length(missing)) install.packages(missing, repos = "https://cloud.r-project.org")

# ---- Step 2: siera, GitHub version, from R-universe ------------------------------
# Always (re)installed: the CRAN release has the same version number (0.5.6),
# so "already installed" can't tell the two apart.

install.packages("siera", repos = c("https://clymbclinical.r-universe.dev",
                                    "https://cloud.r-project.org"))

# Check it is the GitHub version: R-universe records the GitHub commit
sha <- packageDescription("siera")$RemoteSha
if (is.null(sha)) {
  warning("siera looks like the CRAN release, not the GitHub version. ",
          "The demographics table may fail. Run this program again.")
} else {
  message("siera installed from GitHub commit ", substr(sha, 1, 7))
}

# ---- Step 3: Show what is installed --------------------------------------------
# These programs were last run with: siera 0.5.6 (GitHub, commit 9208a9b),
# cards 0.9.0, cardx 0.3.4, tfrmt 0.4.0, gt 1.4.0. Newer versions may change
# the output; the versions actually used are written to logs/run_all.log.

for (p in c("siera", "cards", "cardx", "tfrmt", "gt")) {
  message(sprintf("%-6s %s", p, as.character(packageVersion(p))))
}
