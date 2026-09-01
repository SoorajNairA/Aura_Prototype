module.exports = {
  packagerConfig: {
    name: "AURA",
    executableName: "AURA",
    icon: undefined,
    asar: true,
    // Never include repository metadata or Git marker files in distributable builds.
    ignore: [
      /(^|[\\/])\.git([\\/]|$)/i,
      /(^|[\\/])\.git(ignore|attributes|modules)$/i,
    ],
  },
  makers: [{ name: "@electron-forge/maker-zip", platforms: ["win32"] }],
};
