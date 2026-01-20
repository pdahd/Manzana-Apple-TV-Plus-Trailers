# __Manzana Apple TV Plus Trailers__

A python program to download Apple TV Plus movie and tv-show trailers. Video streams upto 4K with Dolby Vision, HDR10+ and SDR. Audio streams with HE-AAC, AAC, AC-3 and Dolby Atmos (EAC-3 JOC). Audio descriptions are also available. SDH and forced subtitle streams are also available. You can choose what streams you want to download.

<picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/dropcreations/Manzana-Apple-TV-Plus-Trailers/main/assets/manzana__darkmode.png">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/dropcreations/Manzana-Apple-TV-Plus-Trailers/main/assets/manzana__lightmode.png">
    <img alt="Apple TV Plus" src="https://raw.githubusercontent.com/dropcreations/Manzana-Apple-TV-Plus-Trailers/main/assets/manzana__lightmode.png">
</picture>

## __Required__

- [FFmpeg](https://ffmpeg.org/download.html)
- [MP4Box](https://gpac.io)

## Demo

![demo](https://raw.githubusercontent.com/dropcreations/Manzana-Apple-TV-Plus-Trailers/main/assets/usage_demo.gif)

## __How to use?__

First of all clone this project or download the project as a zip file and extract it to your pc.

```
git clone https://github.com/pdahd/Manzana-Apple-TV-Plus-Trailers.git
cd Manzana-Apple-TV-Plus-Trailers
```

Install required modules for python (use `pip3` if `pip` doesn't work for you)

```
pip install -r requirements.txt
```

Now open terminal and run below command (Use `py` or `python3` if `python` doesn't work for you)

```
python manzana.py [url]
```

While downloading streams you will ask what stream you want. When it asked for stream's `ID`, you can use multiple options as mentioned below.

__Video stream__

- You can only select one stream for the ouput, give it's `ID`.

__Audio stream__

- You can select multiple streams or all streams, give `ID`s as a space seperated list or type `all` or `a`. __(ex: 5 2 16 20...)__

__Subtitle stream__

- You can also select multiple streams or all streams if you want. Give `ID`s as a space seperated list or simply type `all` or `a` to get all tracks.

If you don't need audio. just use `--no-audio` or `-an` argument with command

```
python manzana.py --no-audio [url]
```

If you don't need subtitles. just use `--no-subs` or `-sn` argument with command

```
python manzana.py --no-subs [url]
```

This will ask for you what trailer to download when the url has multiple trailers. If you want all, simply type `all` or `a` to select all or type the ID. If you want to downlaod the default trailer in the url without seeing available trailers, use `--default` or `-d` argument with command

```
python manzana.py -d [url]
```

Get help using `-h` or `--help` command

```
usage: manzana.py [-h] [-v] [--list-trailers] [--trailer TRAILER] [-F]
                  [-f FORMAT] [--no-prompt] [-d] [-an] [-sn]
                  url

Manzana: Apple TV Plus Trailers Downloader

positional arguments:
  url                   AppleTV+ URL for a movie or a tv-show.

optional arguments:
  -h, --help            show this help message and exit
  -v, --version         show program's version number and exit
  --list-trailers       list available trailers (t0, t1, ...) and exit
  --trailer TRAILER     select trailer by id (e.g. t0, t1) or "all"
  -F, --list-formats    list available video/audio/subtitle streams and exit
  -f FORMAT, --format FORMAT
                        format selector, e.g. "v0+a0+s4" (use -F to see ids)
  --no-prompt           disable any interactive prompts (CI/Actions friendly)
  -d, --default         get only the default content trailer. (default: False)
  -an, --no-audio       don't download audio streams. (default: False)
  -sn, --no-subs        don't download subtitle streams. (default: False)
```

## __Non-interactive / CI usage (yt-dlp style)__

This fork adds a non-interactive workflow for automation environments (GitHub Actions / scripts / CI),
while keeping the original interactive "select IDs" mode when running in a real terminal.

### List trailers on a page

Some Apple TV pages contain multiple videos (teaser, trailer, clip, featurette, etc.). List them first:

```bash
python manzana.py --list-trailers "<Apple TV URL>"
```

### List formats (streams) for a trailer

List video/audio/subtitle tracks and print the Master M3U8 URL:

```bash
python manzana.py --no-prompt --trailer t0 -F "<Apple TV URL>"
```

### Download by format id (no prompts)

Use the IDs from `-F` output:

```bash
python manzana.py --no-prompt --trailer t0 -f "v6+a0+s4" "<Apple TV URL>"
```

Notes:
- `vN` selects exactly **one** video stream.
- `aN` and `sN` can be multiple (e.g. `v6+a0+a4+s4+s5`).
- In non-interactive mode, if `-f/--format` is not provided, Manzana will exit with an error instead of prompting.
- `--trailer all` will try to apply the same `-f` selector to every trailer on the page. This may fail if some trailers don't have the same tracks.

### GitHub Actions

This repository includes a workflow that can list formats and optionally download the selected streams.
Go to **Actions** → run the workflow and provide:
- `url`
- `trailer` (e.g. `t0`)
- `format` (e.g. `v6+a0+s4`, optional)

## Support

[<img src="https://assets-global.website-files.com/5c14e387dab576fe667689cf/64f1a9ddd0246590df69ea01_kofi_long_button_blue%25402x-p-500.png" alt="ko-fi" width="200">](https://ko-fi.com/dropcodes)

- __NOTE: If you found any issue using this program, mention in issues section__
