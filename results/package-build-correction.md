# Package compile check correction

The first archive check omitted main.aux while retaining main.log and main.bbl.
With `latexmk -g`, the retained log caused bibliography processing to run before
a useful new auxiliary file existed. The observed build failure is retained in
`package-initial-build-failure.log`. No scientific observations were changed.

The archive now retains the matching auxiliary output with the current paper.
The final check additionally removes all auxiliary/bibliography/log/cache outputs
inside a fresh extraction and rebuilds the paper from sources. The final check
compares both extracted PDF text and every page render to the delivered PDF.
