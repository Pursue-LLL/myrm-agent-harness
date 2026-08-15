import sys
import traceback

_original_hook = sys.unraisablehook


def _hook(args):
    obj = args.object
    if obj is not None and hasattr(obj, "cr_frame") and obj.cr_frame is not None:
        print(f"\n>>> UNAWAITED COROUTINE created at: {args.exc_type}", file=sys.stderr)
        traceback.print_stack(obj.cr_frame, file=sys.stderr)
        print(">>> END\n", file=sys.stderr)
    else:
        _original_hook(args)


sys.unraisablehook = _hook
