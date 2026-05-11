Seamly2D Body Measurements Diagram ID-Path Mapping Editor
=========================================================

This is the tool to simplify the process of mapping ID-Path relationship for [Seamly2D interactive body measurements diagram](https://github.com/mlouielu/seamly2d-interactive-body-measurements-diagram).


How To Use
----------

### Editor

1. Open `svg_mapping_editor.html` in the browser
1. Choose body diagram SVG at the left side
1. Choose mapping JSON at the left side
1. Start editing the ID-Path relationship
1. Multiple click on the SVG can cycle the selection through different layer

### Adding hover highlight to body measurement diagram

1. Prepare the mapping JSON
1. Prepare the base body measurements SVG (from [here](https://github.com/mlouielu/seamly2d-interactive-body-measurements-diagram))
1. run `add_svg_hover.py`

```python
python add_svg_hover.py Seamly2d-body-measurements.svg seamly2d_measurement_id_mapping.json out.svg
```


LICENSE
-------

```
The Clear BSD License

Copyright (c) 2023 Louie Lu <git@louie.lu>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted (subject to the limitations in the disclaimer
below) provided that the following conditions are met:

     * Redistributions of source code must retain the above copyright notice,
     this list of conditions and the following disclaimer.

     * Redistributions in binary form must reproduce the above copyright
     notice, this list of conditions and the following disclaimer in the
     documentation and/or other materials provided with the distribution.

     * Neither the name of the copyright holder nor the names of its
     contributors may be used to endorse or promote products derived from this
     software without specific prior written permission.

NO EXPRESS OR IMPLIED LICENSES TO ANY PARTY'S PATENT RIGHTS ARE GRANTED BY
THIS LICENSE. THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND
CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR
BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER
IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
```
