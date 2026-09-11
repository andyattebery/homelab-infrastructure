"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.plugin = exports.details = void 0;

var details = function () { return ({
    name: 'Set Scaled Geometry',
    description: 'Compute the DISPLAY dimensions a VAAPI leaf will produce and publish them as the '
        + 'bsfW and bsfH flow variables, for -bsf:v hevc_metadata=width=...:height=... . '
        + 'pad_vaapi aligns the coded geometry and the bitstream filter restores the display '
        + 'dimensions; without both, Apple players reject the file. The values are not always '
        + '1920x1080, so they cannot be hardcoded. '
        + 'Reads ffprobe data — no re-probe.',
    style: { borderColor: 'orange' },
    tags: '',
    isStartPlugin: false,
    pType: '',
    requiresVersion: '2.11.01',
    sidebarPosition: -1,
    icon: 'faRulerCombined',
    inputs: [
        {
            label: 'Mode',
            name: 'mode',
            type: 'string',
            defaultValue: 'scaled1080',
            inputUI: {
                type: 'dropdown',
                options: ['scaled1080', 'native'],
            },
            tooltip: 'scaled1080: the geometry of w=-2:h=min(1080,ih) — height capped at 1080, '
                + 'width derived to keep the aspect and stay even. Use on a lane that scales.\n'
                + 'native: the source dimensions unchanged. Use on a lane that does not scale.\n'
                + 'Picking the wrong one writes display dimensions that disagree with the picture, '
                + 'and the player trusts the bitstream filter.',
        },
    ],
    outputs: [
        { number: 1, tooltip: 'Geometry computed — bsfW and bsfH set' },
        { number: 2, tooltip: 'No usable width/height on the first video stream' },
    ],
}); };
exports.details = details;

var plugin = function (args) {
    var lib = require('../../../../../methods/lib')();
    args.inputs = lib.loadDefaultValues(args.inputs, details);

    var mode = String(args.inputs.mode);
    var streams = (args.inputFileObj.ffProbeData || {}).streams || [];

    // ffProbeData has NOT been through Begin Command's attached_pic re-typing, so cover art still
    // reports codec_type 'video' here. Skipping it is what stops the geometry being read off a
    // poster image.
    var videoStream = null;
    for (var i = 0; i < streams.length; i++) {
        var s = streams[i];
        if (s.codec_type === 'video' && !(s.disposition && Number(s.disposition.attached_pic) === 1)) {
            videoStream = s;
            break;
        }
    }

    if (!videoStream) {
        args.jobLog('No video stream found — taking output 2');
        return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
    }

    var iw = Number(videoStream.width);
    var ih = Number(videoStream.height);

    if (!(iw > 0) || !(ih > 0)) {
        // Emitting blanks is not an option: Execute drops an empty TOKEN but keeps an argument with
        // an empty VALUE, so hevc_metadata=width=:height= would reach ffmpeg intact.
        args.jobLog('No usable width/height (width=' + videoStream.width
            + ', height=' + videoStream.height + ') — taking output 2');
        return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
    }

    var w;
    var h;
    if (mode === 'native') {
        w = iw;
        h = ih;
    } else {
        // Matches the recipe's awk exactly:
        //   h=($2<1080)?$2:1080; print int($1*h/$2/2+0.5)*2, h
        // Math.round is round-half-up on positives, which is what int(x+0.5) does.
        h = ih < 1080 ? ih : 1080;
        w = Math.round((iw * h / ih) / 2) * 2;
    }

    if (!args.variables.user) {
        args.variables.user = {};
    }
    args.variables.user.bsfW = String(w);
    args.variables.user.bsfH = String(h);

    args.jobLog('Source ' + iw + 'x' + ih + ', mode ' + mode + ' -> display ' + w + 'x' + h);

    return { outputFileObj: args.inputFileObj, outputNumber: 1, variables: args.variables };
};
exports.plugin = plugin;
