"""
Command-line interface for Flashback Termux.
"""

import argparse
import logging
import sys

from .config import load_config, save_config, get_default_config
from .screenshot_worker import TermuxScreenshotWorker
from .window_title_worker import TermuxWindowTitleWorker


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def cmd_screenshot(args):
    """Take a single screenshot."""
    config = load_config()
    setup_logging(args.verbose)

    try:
        worker = TermuxScreenshotWorker(config['screenshot_dir'])

        if config['context_detection']['enabled']:
            title_worker = TermuxWindowTitleWorker()
            context = title_worker.get_current_context()
            path = worker.capture_with_context(context)
            print(f"Screenshot saved: {path}")
            print(f"Context: {context['display_title']}")
        else:
            path = worker.capture()
            print(f"Screenshot saved: {path}")

    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_context(args):
    """Show current app context."""
    setup_logging(args.verbose)

    try:
        worker = TermuxWindowTitleWorker()
        context = worker.get_current_context()

        print(f"App Name: {context['app_name'] or 'N/A'}")
        print(f"App ID: {context['app_id'] or 'N/A'}")
        print(f"Activity: {context['activity'] or 'N/A'}")
        print(f"Display Title: {context['display_title']}")

    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_config(args):
    """Show or reset configuration."""
    import json

    if args.reset:
        defaults = get_default_config()
        save_config(defaults)
        print("Configuration reset to defaults")
        print(f"Config location: {load_config()}")
    else:
        config = load_config()
        print(json.dumps(config, indent=2))


def cmd_server(args):
    """Start the web UI server."""
    config = load_config()
    setup_logging(args.verbose)

    # Import here to avoid early import issues
    from .server import create_app

    app = create_app(config)
    app.run(
        host=config['webui']['host'],
        port=config['webui']['port'],
        debug=args.verbose
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog='flashback-termux',
        description='Android screenshot automation for Termux'
    )
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # screenshot command
    screenshot_parser = subparsers.add_parser('screenshot', help='Take a screenshot')
    screenshot_parser.set_defaults(func=cmd_screenshot)

    # context command
    context_parser = subparsers.add_parser('context', help='Show current app context')
    context_parser.set_defaults(func=cmd_context)

    # config command
    config_parser = subparsers.add_parser('config', help='Show configuration')
    config_parser.add_argument('--reset', action='store_true', help='Reset to defaults')
    config_parser.set_defaults(func=cmd_config)

    # server command
    server_parser = subparsers.add_parser('server', help='Start web UI server')
    server_parser.set_defaults(func=cmd_server)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == '__main__':
    main()
