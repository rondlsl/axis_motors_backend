import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/_pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/widgets/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/features/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/entities/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/shared/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bgPrimary: "var(--clr-bg-primary)",
        bgSecondary: "var(--clr-bg-secondary)",
        bgBlue: "var(--clr-bg-blue)",
        bgDarkBlue: "var(--clr-bg-darkBlue)",
        primary: "var(--clr-primary)",
        typePrimary: "var(--clr-type-primary)",
        typeSecondary: "var(--clr-type-secondary)",
        typeGray: "var(--clr-type-gray)",
        typeRed: "var(--clr-type-red)",
        icon: "var(--clr-icon)",
        border: "var(--clr-border)",
      },
      fontSize: {
        xs: "var(--fz-xs)",
        sm: "var(--fz-sm)",
        md: "var(--fz-md)",
        lg: "var(--fz-lg)",
        xl: "var(--fz-xl)",
        "2xl": "var(--fz-2xl)",
      },
      lineHeight: {
        xs: "var(--lh-xs)",
        sm: "var(--lh-sm)",
        md: "var(--lh-md)",
        lg: "var(--lh-lg)",
        xl: "var(--lh-xl)",
        "2xl": "var(--lh-2xl)",
      },
      fontWeight: {
        thin: "var(--font-thin)",
        extralight: "var(--font-extralight)",
        light: "var(--font-light)",
        normal: "var(--font-normal)",
        medium: "var(--font-medium)",
        semibold: "var(--font-semibold)",
        bold: "var(--font-bold)",
        extrabold: "var(--font-extrabold)",
        black: "var(--font-black)",
      },
      borderRadius: {
        sm: "var(--r-sm)",
        md: "var(--r-md)",
        lg: "var(--r-lg)",
      },
      padding: {
        sm: "var(--p-sm)",
        md: "var(--p-md)",
        lg: "var(--p-lg)",
        "icon-sm": "var(--p-icon-sm)",
        "icon-md": "var(--p-icon-md)",
        "icon-lg": "var(--p-icon-lg)",
      },
      transitionProperty: {
        default: "var(--transition-default)",
      },
      borderWidth: {
        primary: "var(--border-primary)",
      },
    },
  },
  plugins: [],
};

export default config;
