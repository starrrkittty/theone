# Sample pipeline viewer

Open http://127.0.0.1:8801/diagnostics/index.html while the existing server is running.

The viewer contains 10 public skeleton-derived clips and 10 synthetic engineering
fixtures. None includes original RGB video. These exports cannot evaluate the
MediaPipe detector or establish real-video accuracy. Public skeleton conversion
has not been checked against the official loader; visibility values are assumed.
Public derived JSON stays local and is excluded from Git pending license checks.

Each trace contains the input, actual filtered points, candidate/source,
ActionReport, policy, timings, fitted URDF XML, parsed kinematics, completed-set
replay, and B normalization/local rule feedback. Recognition precedes URDF fitting.
The URDF structure and time-varying joint states are separate artifacts.

No API calls are made. Model-generated expert reports and plans are explicitly
marked unexecuted; local rule feedback is not a model-generated report.

To regenerate from the existing evaluation inputs:

```powershell
& 'C:/Users/woshi/anaconda3/python.exe' tools/export_trace_gallery.py
```

The generator writes local artifacts into frontend/public/diagnostics and copies
them into frontend/dist/diagnostics. Rebuilding the frontend also copies the page.
Playback and the seek bar select the frame used by stages 1 through 5; stages 6
through 8 show the complete set. Both individual artifacts and full sample traces
can be downloaded. Angles are measured uncalibrated proxies, not target values.
