"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.plugin = exports.details = void 0;

var details = function () { return ({
    name: 'Check Video Properties',
    description: 'Gate on video width and/or frame rate. '
        + 'Reads ffprobe data — no re-probe needed. '
        + 'All checks are AND: file must pass every enabled check to proceed.',
    style: { borderColor: 'orange' },
    tags: '',
    isStartPlugin: false,
    pType: '',
    requiresVersion: '2.11.01',
    sidebarPosition: -1,
    icon: 'faRulerHorizontal',
    inputs: [
        {
            label: 'Minimum Width (inclusive)',
            name: 'minWidth',
            type: 'string',
            defaultValue: '0',
            inputUI: { type: 'text' },
            tooltip: 'Minimum video width in pixels (inclusive). 0 = no lower bound.',
        },
        {
            label: 'Maximum Width (exclusive)',
            name: 'maxWidth',
            type: 'string',
            defaultValue: '99999',
            inputUI: { type: 'text' },
            tooltip: 'Maximum video width in pixels (exclusive). Files this wide or wider are skipped.',
        },
        {
            label: 'Maximum FPS (exclusive)',
            name: 'maxFps',
            type: 'string',
            defaultValue: '0',
            inputUI: { type: 'text' },
            tooltip: 'Maximum frame rate (exclusive). 0 = no FPS check. '
                + 'Use 50 to exclude 50/59.94/60fps while keeping 24/25/29.97.',
        },
    ],
    outputs: [
        { number: 1, tooltip: 'All checks passed — proceed' },
        { number: 2, tooltip: 'One or more checks failed — file skipped' },
    ],
}); };
exports.details = details;

var plugin = function (args) {
    var lib = require('../../../../../methods/lib')();
    args.inputs = lib.loadDefaultValues(args.inputs, details);

    var minWidth = Number(args.inputs.minWidth) || 0;
    var maxWidth = Number(args.inputs.maxWidth) || 99999;
    var maxFps = Number(args.inputs.maxFps) || 0;

    var streams = (args.inputFileObj.ffProbeData || {}).streams || [];
    var videoStream = null;
    for (var i = 0; i < streams.length; i++) {
        if (streams[i].codec_type === 'video') {
            videoStream = streams[i];
            break;
        }
    }

    if (!videoStream) {
        args.jobLog('No video stream found — skipping');
        return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
    }

    var width = videoStream.width || 0;
    args.jobLog('Video width: ' + width + 'px (range: ' + minWidth + ' <= w < ' + maxWidth + ')');

    if (width < minWidth || width >= maxWidth) {
        args.jobLog('Width out of range — skipping');
        return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
    }

    if (maxFps > 0) {
        var fps = 0;
        var rFrameRate = videoStream.r_frame_rate || '';
        if (rFrameRate) {
            var parts = rFrameRate.split('/');
            if (parts.length === 2) {
                var num = Number(parts[0]);
                var den = Number(parts[1]);
                if (den > 0) {
                    fps = num / den;
                }
            }
        }

        args.jobLog('Video FPS: ' + fps.toFixed(3) + ' (r_frame_rate: ' + rFrameRate + ', max: ' + maxFps + ')');

        if (fps <= 0 || fps >= maxFps) {
            args.jobLog('FPS out of range — skipping');
            return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
        }
    }

    args.jobLog('All checks passed — proceeding');
    return { outputFileObj: args.inputFileObj, outputNumber: 1, variables: args.variables };
};
exports.plugin = plugin;
