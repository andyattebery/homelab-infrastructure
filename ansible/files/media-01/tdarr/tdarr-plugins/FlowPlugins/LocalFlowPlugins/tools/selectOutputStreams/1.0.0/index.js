"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.plugin = exports.details = void 0;

var details = function () { return ({
    name: 'Select Output Streams',
    description: 'Choose which video and audio streams the output carries, by marking the rest '
        + 'removed on the FFmpeg command. '
        + 'Audio selection is default-disposition WITH A FALLBACK to the first audio stream — '
        + 'the community Remove Stream By Property plugin has no fallback, so on a file that '
        + 'flags no default it removes every audio stream and the file ships silent. '
        + 'Also publishes selectedAudioCodec as a flow variable so a later copy-vs-encode branch '
        + 'can test the stream actually kept rather than the whole file. '
        + 'Also selects subtitles: text kept, bitmap removed, because a bitmap subtitle reaching '
        + 'an -c:s mov_text leaf fails the entire encode rather than being skipped. '
        + 'Requires Begin Command before it. Does not touch data streams.',
    style: { borderColor: 'orange' },
    tags: '',
    isStartPlugin: false,
    pType: '',
    requiresVersion: '2.11.01',
    sidebarPosition: -1,
    icon: 'faFilter',
    inputs: [
        {
            label: 'Audio Mode',
            name: 'audioMode',
            type: 'string',
            defaultValue: 'defaultWithFallback',
            inputUI: {
                type: 'dropdown',
                options: ['defaultWithFallback', 'firstOnly'],
            },
            tooltip: 'defaultWithFallback: keep every stream flagged default, or the first audio '
                + 'stream if none is flagged. A file flagging two defaults keeps both and ships '
                + 'two tracks.\n'
                + 'firstOnly: keep exactly one stream — the first flagged default, else the first '
                + 'audio stream. Drops a legitimate second default track.',
        },
        {
            label: 'Keep First Video Stream Only',
            name: 'keepFirstVideoOnly',
            type: 'boolean',
            defaultValue: 'true',
            inputUI: { type: 'switch' },
            tooltip: 'On: only the first video stream is mapped. '
                + 'Off: a second video track (dual-track Dolby Vision, for example) is also mapped, '
                + 'and the lane\'s -c:v then tries to encode it.',
        },
        {
            label: 'Subtitle Mode',
            name: 'subtitleMode',
            type: 'string',
            defaultValue: 'textOnly',
            inputUI: {
                type: 'dropdown',
                options: ['textOnly', 'none'],
            },
            tooltip: 'textOnly: keep text subtitles, remove bitmap ones.\n'
                + 'none: remove every subtitle stream.\n'
                + 'Bitmap subtitles must never reach an mp4 leaf that encodes -c:s mov_text: '
                + 'ffmpeg FAILS THE WHOLE ENCODE rather than skipping them — "Subtitle encoding '
                + 'currently only possible from text to text or bitmap to bitmap." A title left '
                + 'with no text subtitles is the same as -sn.',
        },
        {
            label: 'Drop Attachments',
            name: 'dropAttachments',
            type: 'boolean',
            defaultValue: 'true',
            inputUI: { type: 'switch' },
            tooltip: 'On: attachment streams are removed. Begin Command re-types embedded cover art '
                + 'to attachment, and mp4 will not carry it. '
                + 'Off: the mux is attempted with them and can fail.',
        },
    ],
    outputs: [
        { number: 1, tooltip: 'Streams selected' },
        { number: 2, tooltip: 'File has no audio streams at all' },
    ],
}); };
exports.details = details;

var plugin = function (args) {
    var lib = require('../../../../../methods/lib')();
    args.inputs = lib.loadDefaultValues(args.inputs, details);

    // Checked here rather than via FlowHelpers so this plugin has no cross-tree require.
    if (!args.variables || !args.variables.ffmpegCommand || !args.variables.ffmpegCommand.init) {
        var msg = 'FFmpeg command not initialised. Put the "Begin Command" plugin before this one.';
        args.jobLog(msg);
        throw new Error(msg);
    }

    // String comparison, not truthiness: a boolean input arrives as the STRING 'false' when the
    // switch is off, and 'false' is truthy.
    var audioMode = String(args.inputs.audioMode);
    var keepFirstVideoOnly = String(args.inputs.keepFirstVideoOnly) === 'true';
    var dropAttachments = String(args.inputs.dropAttachments) === 'true';
    var subtitleMode = String(args.inputs.subtitleMode);

    var streams = args.variables.ffmpegCommand.streams;

    // Begin Command re-types any stream with disposition.attached_pic to 'attachment', so cover art
    // is already out of this list and video[0] is the real first video stream.
    var video = streams.filter(function (s) { return s.codec_type === 'video'; });
    var audio = streams.filter(function (s) { return s.codec_type === 'audio'; });
    var attachments = streams.filter(function (s) { return s.codec_type === 'attachment'; });

    args.jobLog('Streams: ' + video.length + ' video, ' + audio.length + ' audio, '
        + attachments.length + ' attachment');

    if (audio.length === 0) {
        args.jobLog('No audio streams found — taking output 2. '
            + 'Continuing here would ship a silent file, which is the defect this plugin exists '
            + 'to remove.');
        return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
    }

    var flaggedDefault = audio.filter(function (s) {
        return s.disposition && Number(s.disposition.default) === 1;
    });

    var keep;
    if (flaggedDefault.length > 0) {
        keep = flaggedDefault;
        args.jobLog('Audio: ' + keep.length + ' stream(s) flagged default');
    } else {
        // THE FALLBACK. Roughly a fifth of the kids library flags no default audio at all.
        keep = [audio[0]];
        args.jobLog('Audio: nothing flagged default — falling back to the first audio stream');
    }

    if (audioMode === 'firstOnly' && keep.length > 1) {
        args.jobLog('Audio mode firstOnly — narrowing ' + keep.length + ' kept streams to 1');
        keep = [keep[0]];
    }

    audio.forEach(function (s) {
        if (keep.indexOf(s) === -1) {
            s.removed = true;
            args.jobLog('  removing audio stream index ' + s.index + ' (' + s.codec_name + ')');
        } else {
            args.jobLog('  keeping audio stream index ' + s.index + ' (' + s.codec_name + ')');
        }
    });

    if (keepFirstVideoOnly) {
        video.forEach(function (s, i) {
            if (i > 0) {
                s.removed = true;
                args.jobLog('  removing extra video stream index ' + s.index
                    + ' (' + s.codec_name + ')');
            }
        });
    }

    // Text codecs mp4 can carry via mov_text. Anything else in a subtitle stream is bitmap and
    // must go: hdmv_pgs_subtitle, dvd_subtitle, dvb_subtitle and xsub are the ones seen here, but
    // the test is an allow-list so an unknown bitmap codec fails safe rather than reaching ffmpeg.
    var TEXT_SUBTITLE_CODECS = ['subrip', 'ass', 'ssa', 'mov_text', 'webvtt', 'text'];
    var subtitles = streams.filter(function (s) { return s.codec_type === 'subtitle'; });
    subtitles.forEach(function (s) {
        var codec = String(s.codec_name || '').toLowerCase();
        var keep = subtitleMode === 'textOnly' && TEXT_SUBTITLE_CODECS.indexOf(codec) !== -1;
        if (keep) {
            args.jobLog('  keeping subtitle stream index ' + s.index + ' (' + codec + ')');
        } else {
            s.removed = true;
            args.jobLog('  removing subtitle stream index ' + s.index + ' (' + codec + ')'
                + (subtitleMode === 'textOnly' ? ' — bitmap, would fail the encode' : ''));
        }
    });
    args.jobLog('Subtitles: %d of %d kept'
        .replace('%d', String(subtitles.filter(function (s) { return !s.removed; }).length))
        .replace('%d', String(subtitles.length)));

    if (dropAttachments) {
        attachments.forEach(function (s) {
            s.removed = true;
            args.jobLog('  removing attachment stream index ' + s.index);
        });
    }

    if (!args.variables.user) {
        args.variables.user = {};
    }
    // The codec of the stream actually kept. checkAudioCodec asks whether the FILE has an aac
    // stream anywhere, which sends an AC3-default / AAC-commentary source down the copy branch.
    args.variables.user.selectedAudioCodec = String(keep[0].codec_name || '');
    args.jobLog('selectedAudioCodec = ' + args.variables.user.selectedAudioCodec);

    return { outputFileObj: args.inputFileObj, outputNumber: 1, variables: args.variables };
};
exports.plugin = plugin;
