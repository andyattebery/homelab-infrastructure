"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.plugin = exports.details = void 0;
const fs = require("fs");

const details = () => ({
    name: 'Keep Original Date',
    description: 'Copies the original file modification date to the current working file. '
        + 'Place after Replace Original File.',
    style: { borderColor: 'green' },
    tags: '',
    isStartPlugin: false,
    pType: '',
    requiresVersion: '2.11.01',
    sidebarPosition: -1,
    icon: 'faClock',
    inputs: [],
    outputs: [
        { number: 1, tooltip: 'Success' },
        { number: 2, tooltip: 'Failed to set date' },
    ],
});
exports.details = details;

const plugin = async (args) => {
    const lib = require('../../../../../methods/lib')();
    args.inputs = lib.loadDefaultValues(args.inputs, details);

    const stat = args.originalLibraryFile.statSync;
    if (!stat || !stat.mtimeMs) {
        args.jobLog('No original mtime available — skipping');
        return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
    }

    const filePath = args.inputFileObj._id;
    const mtimeSec = stat.mtimeMs / 1000;

    try {
        await fs.promises.utimes(filePath, mtimeSec, mtimeSec);
        const d = new Date(stat.mtimeMs);
        args.jobLog(`Set mtime on ${filePath} to ${d.toISOString()}`);
        return { outputFileObj: args.inputFileObj, outputNumber: 1, variables: args.variables };
    } catch (err) {
        args.jobLog(`Failed to set mtime: ${err.message}`);
        return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
    }
};
exports.plugin = plugin;
