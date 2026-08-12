# UI Page Turn - StarNinjas CC0

This optional content pack contains ten real book-page recordings for local,
model-free UI Foley. It is intentionally separate from the Gate A add-on and
is not included in the `0.1.0-rc1` add-on, demo archive, or exported Gate A
PCK. Games may copy the pack explicitly under its separate CC0 provenance.

The recordings come from StarNinjas' **10 Book Page Flips** upload on
[OpenGameArt](https://opengameart.org/content/10-book-page-flips). The exact
download archive is
[`book_flips_-_starninjas.zip`](https://opengameart.org/sites/default/files/book_flips_-_starninjas.zip),
whose SHA-256 is recorded in `asset-rights.json`.

The source page marks the upload as
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). Attribution is
not required, although the uploader says credit is appreciated. Keep
`asset-rights.json` with any redistributed copy so provenance is not lost.
The author and OpenGameArt do not endorse SonicMatter.

## Use in Godot

Copy the `audio` directory into a Godot project and preload whichever variants
fit the interaction. The files are ordinary stereo Ogg Vorbis assets at
44.1 kHz; playback needs no Python, model, network service, GPU, or SonicMatter
runtime code.

The recordings range from about 0.60 to 1.13 seconds. Do not force them into a
shorter UI duration merely to match a visual tween: start the cue at the
semantic transition boundary and allow its natural tail to finish, or make a
reviewed derivative with the transform recorded in a new rights manifest.
