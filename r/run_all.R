#==============================================================================
# Study        : CDISCPILOT01 (CDISC SDTM/ADaM Pilot Project)
# Program      : run_all.R
# Output       : rtf/ (all three tables), logs/run_all.log
# Title        : Run the whole ARS-to-RTF pipeline
#
# Purpose      : Run every step in order, from this folder:
#                  ARS file --(siera)--> ARD programmes --(cards)--> ARDs
#                  --(tfrmt + gt)--> RTF tables
#                and keep a log of the run: date, R and package versions,
#                a fingerprint (MD5) of every input, every check and its
#                result, and any error.
# Inputs       : ars/, adam/ and the programs listed below
# Outputs      : rtf/t14-1-1-demog.rtf
#                rtf/t14-3-1-1-teae-summ.rtf
#                rtf/t14-3-3-1-vitals-chgbl.rtf
#                logs/run_all.log
# Packages     : as the programs below
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

# The programs to run, in order
programs <- c("01_make_ard_programs.R",
              "t14-1-1-demog.R",
              "t14-3-1-1-teae.R",
              "t14-3-3-1-vitals.R")

# ---- Step 1: Start the log ----------------------------------------------------
# Everything printed, every message and every warning goes into the log file.

dir.create("logs", showWarnings = FALSE)

# No progress bars when reading the data: they only clutter the log
options(readr.show_progress = FALSE)
log_file <- file.path("logs", "run_all.log")
log_con <- file(log_file, open = "wt")
sink(log_con)
sink(log_con, type = "message")

cat("Run started : ", format(Sys.time(), "%d%b%Y %H:%M:%S %Z"), "\n", sep = "")
cat("Folder      : ", getwd(), "\n", sep = "")
cat("R version   : ", R.version.string, "\n", sep = "")
cat("Run by      : ", Sys.info()[["user"]], " on ", Sys.info()[["nodename"]], "\n\n", sep = "")

# Fingerprint every input, so the run can be tied to the exact files used
inputs <- c(list.files("ars", full.names = TRUE), list.files("adam", full.names = TRUE),
            "common.R", programs)
cat("Input files (MD5):\n")
print(data.frame(md5 = unname(tools::md5sum(inputs)), file = inputs), row.names = FALSE)
cat("\n")

# ---- Step 2: Run each program --------------------------------------------------
# Each table runs in its own environment, so nothing is shared by accident.
# If any step fails (including a QC check), the run stops and says why.

status <- tryCatch({
  for (program in programs) {
    cat("==== ", program, " ====\n", sep = "")
    withCallingHandlers(
      source(program, local = new.env()),
      warning = function(w) cat("WARNING: ", conditionMessage(w), "\n", sep = "")
    )
    cat("\n")
  }
  "completed"
}, error = function(e) {
  cat("ERROR: ", conditionMessage(e), "\n", sep = "")
  "FAILED"
})

# ---- Step 3: Record the outputs and package versions, and close the log ------

cat("Outputs:\n")
outputs <- list.files("rtf", full.names = TRUE)
print(data.frame(file = outputs, bytes = file.size(outputs),
                 written = format(file.mtime(outputs), "%d%b%Y %H:%M:%S")),
      row.names = FALSE)

cat("\nPackage versions:\n")
key_packages <- c("siera", "cards", "cardx", "tfrmt", "gt", "dplyr", "tidyr", "readr", "jsonlite")
print(data.frame(package = key_packages,
                 version = vapply(key_packages, function(p) as.character(packageVersion(p)), "")),
      row.names = FALSE)
cat("\n")
print(sessionInfo())

cat("\nRun ", status, ": ", format(Sys.time(), "%d%b%Y %H:%M:%S %Z"), "\n", sep = "")
sink(type = "message")
sink()
close(log_con)

# RStudio adds hidden colour codes to messages (they show as "G3;" and "g" in
# a text editor). Remove them, so the log is plain text.
log_text <- readLines(log_file, warn = FALSE)
codes <- "\033(\\[[0-9;]*[A-Za-z]|\\][^\a]*\a|G[0-9]*;|g)"
code_only <- grepl("\033", log_text) & gsub(codes, "", log_text) == ""
log_text <- gsub(codes, "", log_text[!code_only])
writeLines(log_text, log_file)

# Tell the person running it how it went
if (status == "FAILED") stop("The run failed. See ", log_file)
message("Done. The tables are in rtf/ and the log is ", log_file)
