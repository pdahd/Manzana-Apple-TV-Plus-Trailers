import argparse
from rich.traceback import install
from core import run

install()

VERSION = '2.3.0'
LOGO = r"""


    $$$$$$\$$$$\   $$$$$$\  $$$$$$$\  $$$$$$$$\ $$$$$$\  $$$$$$$\   $$$$$$\  
    $$  _$$  _$$\  \____$$\ $$  __$$\ \____$$  |\____$$\ $$  __$$\  \____$$\ 
    $$ / $$ / $$ | $$$$$$$ |$$ |  $$ |  $$$$ _/ $$$$$$$ |$$ |  $$ | $$$$$$$ |
    $$ | $$ | $$ |$$  __$$ |$$ |  $$ | $$  _/  $$  __$$ |$$ |  $$ |$$  __$$ |
    $$ | $$ | $$ |\$$$$$$$ |$$ |  $$ |$$$$$$$$\\$$$$$$$ |$$ |  $$ |\$$$$$$$ |
    \__| \__| \__| \_______|\__|  \__|\________|\_______|\__|  \__| \_______|

                        ──── Apple TV Plus Trailers ────


"""

def main():
    parser = argparse.ArgumentParser(
        description="Manzana: Apple TV Plus Trailers Downloader"
    )
    parser.add_argument(
        '-v',
        '--version',
        version=f"Manzana: Apple TV Plus Trailers {VERSION}",
        action="version"
    )

    # Trailer selection
    parser.add_argument(
        '--list-trailers',
        dest="listTrailers",
        help="list available trailers (t0, t1, ...) and exit",
        action="store_true"
    )
    parser.add_argument(
        '--trailer',
        dest="trailer",
        help='select trailer by id (e.g. t0, t1) or "all". If not provided, will prompt in TTY unless --no-prompt.',
        type=str,
        default=None
    )

    # Format listing / selection (yt-dlp style)
    parser.add_argument(
        '-F',
        '--list-formats',
        dest="listFormats",
        help="list available video/audio/subtitle streams and exit",
        action="store_true"
    )
    parser.add_argument(
        '-f',
        '--format',
        dest="format",
        help='format selector, e.g. "v0+a1+s0" (use -F to see ids)',
        type=str,
        default=None
    )
    parser.add_argument(
        '--no-prompt',
        dest="noPrompt",
        help="disable any interactive prompts (CI/Actions friendly)",
        action="store_true"
    )

    # Existing options
    parser.add_argument(
        '-d',
        '--default',
        dest="default",
        help="get only the default content trailer. (default: False)",
        action="store_true"
    )
    parser.add_argument(
        '-an',
        '--no-audio',
        dest="noAudio",
        help="don't download audio streams. (default: False)",
        action="store_true"
    )
    parser.add_argument(
        '-sn',
        '--no-subs',
        dest="noSubs",
        help="don't download subtitle streams. (default: False)",
        action="store_true"
    )

    parser.add_argument(
        'url',
        help="AppleTV+ URL for a movie or a tv-show.",
        type=str
    )
    args = parser.parse_args()
    run(args)

if __name__ == "__main__":
    print(LOGO)
    main()
