import os, sys, site

BASE_DIR = os.path.dirname(__file__)
VENDOR = os.path.join(BASE_DIR, "lib", "optuna")

# Gör katalogen till en giltig site-packages
site.addsitedir(VENDOR)
