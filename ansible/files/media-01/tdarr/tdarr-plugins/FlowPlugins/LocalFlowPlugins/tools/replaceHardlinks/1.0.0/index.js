"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.plugin = exports.details = void 0;
const path = require("path");

function cifsToNas(cifsPath) {
    if (!cifsPath.startsWith('/media-raw/')) {
        throw new Error(`Path does not start with /media-raw/: ${cifsPath}`);
    }
    return `/mnt/data/${cifsPath.substring('/media-raw/'.length)}`;
}

async function callApi(apiUrl, endpoint, payload) {
    const url = apiUrl.replace(/\/+$/, '') + endpoint;
    const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(600000),
    });
    if (!response.ok) {
        const text = await response.text();
        throw new Error(`HTTP ${response.status} from ${url}: ${text}`);
    }
    return response.json();
}

const details = () => ({
    name: 'Replace Hardlinks',
    description: 'Replace hardlink siblings by calling the hardlink-manager API on the NAS. '
        + 'Must run after Replace Original File in the flow. '
        + 'Reads sibling paths stored by the Detect Hardlinks plugin.',
    style: { borderColor: 'green' },
    tags: '',
    isStartPlugin: false,
    pType: '',
    requiresVersion: '2.11.01',
    sidebarPosition: -1,
    icon: 'faLink',
    inputs: [
        {
            label: 'API URL',
            name: 'apiUrl',
            type: 'string',
            defaultValue: 'https://hardlink-manager.{{ domain_name }}',
            inputUI: { type: 'text' },
            tooltip: 'URL of the hardlink-manager API on the NAS.',
        },
    ],
    outputs: [
        { number: 1, tooltip: 'Success (or no hardlinks to process)' },
        { number: 2, tooltip: 'One or more hardlink replacements failed' },
    ],
});
exports.details = details;

const plugin = async (args) => {
    const lib = require('../../../../../methods/lib')();
    args.inputs = lib.loadDefaultValues(args.inputs, details);

    const apiUrl = String(args.inputs.apiUrl || '').trim();
    if (!apiUrl) {
        throw new Error('apiUrl input is required');
    }

    const siblingsJson = (args.variables.user || {}).hardlinkSiblings;

    if (!siblingsJson) {
        args.jobLog('No hardlink siblings in flow variables — skipping');
        return { outputFileObj: args.inputFileObj, outputNumber: 1, variables: args.variables };
    }

    let siblings;
    try {
        siblings = JSON.parse(siblingsJson);
    } catch (e) {
        args.jobLog(`Failed to parse hardlinkSiblings: ${siblingsJson}`);
        return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
    }

    if (!Array.isArray(siblings) || siblings.length === 0) {
        args.jobLog('Empty sibling list — skipping');
        return { outputFileObj: args.inputFileObj, outputNumber: 1, variables: args.variables };
    }

    const cifsPrimaryPath = args.inputFileObj._id;
    const nasPrimaryPath = cifsToNas(cifsPrimaryPath);
    const newExt = path.extname(nasPrimaryPath);
    const oldExt = path.extname(siblings[0]);

    args.jobLog(`New primary (CIFS): ${cifsPrimaryPath}`);
    args.jobLog(`New primary (NAS): ${nasPrimaryPath}`);
    args.jobLog(`Replacing ${siblings.length} sibling(s), old ext: ${oldExt} -> new ext: ${newExt}`);

    const data = await callApi(apiUrl, '/replace', {
        new_primary: nasPrimaryPath,
        old_ext: oldExt,
        new_ext: newExt,
        siblings: siblings,
    });

    const results = data.details || [];
    for (const r of results) {
        if (r.result === 'ok') {
            args.jobLog(`  Replaced: ${r.sibling} -> ${r.new_path || r.sibling}`);
        } else {
            args.jobLog(`  ERROR on ${r.sibling}: ${r.message || 'unknown error'}`);
        }
    }

    if (data.status !== 'ok') {
        args.jobLog(`${data.errors || 0}/${siblings.length} replacement(s) failed`);
        return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
    }

    args.jobLog(`All ${siblings.length} sibling(s) replaced successfully`);
    return { outputFileObj: args.inputFileObj, outputNumber: 1, variables: args.variables };
};
exports.plugin = plugin;
