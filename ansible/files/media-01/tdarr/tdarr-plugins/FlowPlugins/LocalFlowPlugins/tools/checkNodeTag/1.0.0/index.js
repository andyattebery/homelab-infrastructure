"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.plugin = exports.details = void 0;

var details = function () { return ({
    name: 'Check Node Tag',
    description: 'Branch on the Node Tags of the node running this job. Flow plugins execute '
        + 'inside the node that picked the file up, so args.nodeTags is that node\'s own label.\n\n'
        + 'Use this to select settings measured on a SPECIFIC CARD. Encoder, vendor and '
        + 'architecture are all abstractions above the thing that was measured — -qp 15 is a '
        + 'property of an A4000, not of hevc_nvenc, and two cards that share an encoder do not '
        + 'share its settings.\n\n'
        + 'Prefer this over checkNodeHardwareEncoder, which answers by running a real one-second '
        + 'test encode on every job and cannot separate two vendors implementing the same encoder '
        + '— an Intel Arc and an AMD card both pass a hevc_vaapi probe.\n\n'
        + 'Node Tags are set in the Node Options panel, or over the API: '
        + 'POST /api/v2/update-node {"data":{"nodeID":"<id>","nodeUpdates":{"nodeTags":"..."}}}. '
        + 'Resolve the nodeID from /api/v2/get-nodes at run time — node IDs are NOT stable across '
        + 'restarts.',
    style: { borderColor: 'orange' },
    tags: '',
    isStartPlugin: false,
    pType: '',
    requiresVersion: '2.20.01',
    sidebarPosition: -1,
    icon: 'faTag',
    inputs: [
        {
            label: 'Tags',
            name: 'tags',
            type: 'string',
            defaultValue: '',
            inputUI: { type: 'text' },
            tooltip: 'Comma-separated. Output 1 if the node carries ANY of them.\n'
                + 'List more than one only where a single measurement is known to cover both '
                + 'cards — otherwise one card silently inherits the other\'s settings.',
        },
    ],
    outputs: [
        { number: 1, tooltip: 'Node carries one of these tags' },
        { number: 2, tooltip: 'It does not — including when the node reports no tags at all' },
    ],
}); };
exports.details = details;

var plugin = function (args) {
    var lib = require('../../../../../methods/lib')();
    args.inputs = lib.loadDefaultValues(args.inputs, details);

    var wanted = String(args.inputs.tags || '').split(',')
        .map(function (t) { return t.trim().toLowerCase(); })
        .filter(function (t) { return t.length > 0; });

    // nodeTags is OPTIONAL in IpluginInputArgs and only exists from Tdarr 2.20.01 — the version
    // the upstream tagsWorkerType plugin, the only other consumer of the field, requires.
    // An absent field and an empty one are DIFFERENT failures and must not be collapsed into
    // output 2: silently routing every job on an old node to the no-leaf terminal produces a
    // library-wide error run whose cause is invisible in the job log. Name it instead.
    if (args.nodeTags === undefined || args.nodeTags === null) {
        var absent = 'This node did not provide nodeTags. Either it runs Tdarr older than '
            + '2.20.01, where the field does not exist in plugin args, or it reported no tags '
            + 'at all. Upgrade the node, or tag it. Routing in this flow is by node tag, so '
            + 'there is no safe branch to take without one.';
        args.jobLog(absent);
        throw new Error(absent);
    }

    // args.nodeTags is a comma-joined string set on the node, so this is a membership test.
    // The community checkFlowVariable cannot do it: it compares the WHOLE value against a
    // comma-split candidate list, so a node tagged "mapped,a4000" matches neither candidate.
    var have = String(args.nodeTags).split(',')
        .map(function (t) { return t.trim().toLowerCase(); })
        .filter(function (t) { return t.length > 0; });

    args.jobLog('node tags: ' + (have.length ? have.join(',') : '(none)')
        + '   looking for: ' + (wanted.length ? wanted.join(',') : '(none configured)'));

    if (wanted.length === 0) {
        // An unconfigured node would otherwise match everything and send every job down one leaf.
        var msg = 'Check Node Tag has no tags configured. Set them, or remove the node.';
        args.jobLog(msg);
        throw new Error(msg);
    }

    var match = have.some(function (t) { return wanted.indexOf(t) !== -1; });

    // An untagged node takes output 2, the same exit as a card this flow has no leaf for. Both
    // mean "nothing here was measured for you", and both must stay away from an encode.
    args.jobLog(match ? 'match — taking output 1' : 'no match — taking output 2');

    return { outputFileObj: args.inputFileObj, outputNumber: match ? 1 : 2, variables: args.variables };
};
exports.plugin = plugin;
