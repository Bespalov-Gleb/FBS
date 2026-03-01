import { createTheme } from '@mui/material/styles';

const palette = {
  sidebar: {
    dark: '#2d3748',
    lighter: '#4a5568',
  },
  content: {
    primary: '#ffffff',
    secondary: '#f7fafc',
  },
  accent: {
    blue: '#3182ce',
    green: '#38a169',
    red: '#e53e3e',
    pink: '#ed64a6',
  },
  text: {
    primary: '#1a202c',
    secondary: '#718096',
    onDark: '#ffffff',
  },
};

export const theme = createTheme({
  palette: {
    primary: {
      main: palette.accent.blue,
    },
    secondary: {
      main: palette.sidebar.lighter,
    },
    success: {
      main: palette.accent.green,
    },
    error: {
      main: palette.accent.red,
    },
    background: {
      default: palette.content.secondary,
      paper: palette.content.primary,
    },
    text: {
      primary: palette.text.primary,
      secondary: palette.text.secondary,
    },
  },
  typography: {
    h4: {
      fontWeight: 600,
    },
    body1: {},
    body2: {
      color: palette.text.secondary,
    },
    subtitle2: {},
  },
});

export { palette };
