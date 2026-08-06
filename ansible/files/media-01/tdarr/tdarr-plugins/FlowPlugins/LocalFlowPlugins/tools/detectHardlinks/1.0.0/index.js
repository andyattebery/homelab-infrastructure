"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.plugin = exports.details = void 0;

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
    name: 'Detect Hardlinks',
    description: 'Detect hardlinks by calling the hardlink-manager API on the NAS. '
        + 'Stores sibling paths in flow variables for the Replace Hardlinks plugin. '
        + 'Requires the Tdarr library source to be a per-disk CIFS mount (/media-raw/dataXX).',
    style: { borderColor: 'orange' },
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
        {
            label: 'Search Root',
            name: 'searchRoot',
            type: 'string',
            defaultValue: '',
            inputUI: { type: 'text' },
            tooltip: 'NAS-local root path to search for hardlink siblings '
                + '(e.g. /mnt/data/data05/.f). Leave empty to auto-detect from the file path.',
        },
    ],
    outputs: [
        { number: 1, tooltip: 'File has hardlinks (siblings stored in flow variables)' },
        { number: 2, tooltip: 'No hardlinks detected' },
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

    const cifsPath = args.originalLibraryFile._id;

    let searchRoot = String(args.inputs.searchRoot || '').trim();
    if (!searchRoot) {
        const parts = cifsPath.split('/').filter((p) => p.length > 0);
        if (parts.length < 4) {
            args.jobLog(`File path too shallow to auto-detect search root: ${cifsPath}`);
            return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
        }
        searchRoot = cifsToNas(`/${parts[0]}/${parts[1]}/${parts[2]}`);
    }

    const nasFilePath = cifsToNas(cifsPath);

    args.jobLog(`File: ${cifsPath}`);
    args.jobLog(`NAS path: ${nasFilePath}`);
    args.jobLog(`Search root: ${searchRoot}`);

    const data = await callApi(apiUrl, '/detect', {
        file_path: nasFilePath,
        search_root: searchRoot,
    });

    if (data.status !== 'ok') {
        throw new Error(`Hardlink detect failed: ${data.message || JSON.stringify(data)}`);
    }

    if (data.warnings) {
        args.jobLog(`API warnings: ${data.warnings}`);
    }

    args.jobLog(`Inode: ${data.inode}`);

    const allSiblings = data.siblings || [];
    const orphans = allSiblings.filter((s) => s.endsWith('.hlbak') || s.endsWith('.partial.old'));
    const siblings = allSiblings.filter((s) => !s.endsWith('.hlbak') && !s.endsWith('.partial.old'));

    if (orphans.length > 0) {
        args.jobLog(`Filtered ${orphans.length} orphan(s) from siblings:`);
        for (const o of orphans) {
            args.jobLog(`  orphan: ${o}`);
        }
    }

    if (siblings.length === 0) {
        args.jobLog('No hardlink siblings found');
        return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
    }

    if (!args.variables.user) {
        args.variables.user = {};
    }
    args.variables.user.hardlinkSiblings = JSON.stringify(siblings);

    args.jobLog(`Found ${siblings.length} hardlink sibling(s):`);
    for (const sib of siblings) {
        args.jobLog(`  ${sib}`);
    }

    return { outputFileObj: args.inputFileObj, outputNumber: 1, variables: args.variables };
};
exports.plugin = plugin;
