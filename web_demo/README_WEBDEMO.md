# web_demo

* `airwrite.html` - live camera hand tracking (MediaPipe), air-writing, recognition, message builder.
* `recognizer.js` - glyph-template recognizer (NOT a trained model). `test/` has the synthetic sanity test.
* `parkiscribe.html` - earlier standalone page (pointer capture, recordings, research view).

Run (needs internet for MediaPipe files):
    cd web_demo && python3 -m http.server 8080
    open http://localhost:8080/airwrite.html
Optional offline model: put hand_landmarker.task in web_demo/models/.

Synthetic sanity test: `cd test && python3 make_samples.py && NODE_PATH=<node_modules with canvas> node run.js`
