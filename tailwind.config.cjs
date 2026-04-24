module.exports = {
  content: [
    "./web/Pages/**/*.cshtml",
    "./web/wwwroot/js/**/*.js",
    "./node_modules/tw-elements/js/**/*.js",
  ],
  darkMode: "class",
  plugins: [require("tw-elements/plugin.cjs")],
};
