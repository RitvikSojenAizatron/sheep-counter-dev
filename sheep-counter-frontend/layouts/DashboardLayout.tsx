import { useState } from 'react';
import { Outlet, Link as RouterLink, useLocation } from 'react-router-dom';
import {
  AppBar,
  Toolbar,
  Typography,
  Box,
  Drawer,
  List,
  ListItemButton,
  ListItemText,
  IconButton,
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import VisibilityIcon from '@mui/icons-material/Visibility';
import SettingsIcon from '@mui/icons-material/Settings';
import AssessmentIcon from '@mui/icons-material/Assessment';
import TimelineIcon from '@mui/icons-material/Timeline';
import VideocamIcon from '@mui/icons-material/Videocam';
import MemoryIcon from '@mui/icons-material/Memory';
import RuleIcon from '@mui/icons-material/Rule';

const drawerWidth = 240;

export const DashboardLayout = () => {
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(true);

  const navItems = [
    { label: 'Live', icon: <VideocamIcon />, path: '/dashboard/live' },
    { label: 'Events', icon: <TimelineIcon />, path: '/dashboard/events' },
    {
      label: 'Analytics',
      icon: <AssessmentIcon />,
      path: '/dashboard/analytics',
    },
    { label: 'Cameras', icon: <VisibilityIcon />, path: '/admin/cameras' },
    { label: 'Rules', icon: <RuleIcon />, path: '/admin/rules' },
    { label: 'System', icon: <SettingsIcon />, path: '/admin/system' },
    { label: 'IO Control', icon: <MemoryIcon />, path: '/admin/control' },
  ];

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <AppBar
        position="fixed"
        sx={{
          zIndex: (theme) => theme.zIndex.drawer + 1,
          width: '100%',
          ml: 0,
        }}
      >
        <Toolbar
          sx={{
            pl: drawerOpen ? `${drawerWidth}px` : 0,
            transition: (theme) =>
              theme.transitions.create('padding-left', {
                easing: theme.transitions.easing.sharp,
                duration: theme.transitions.duration.enteringScreen,
              }),
          }}
        >
          <IconButton
            color="inherit"
            edge="start"
            onClick={() => setDrawerOpen((open) => !open)}
          >
            <MenuIcon />
          </IconButton>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Sheep Counter
          </Typography>
        </Toolbar>
      </AppBar>
      <Drawer
        variant="persistent"
        open={drawerOpen}
        sx={{
          width: drawerOpen ? drawerWidth : 0,
          flexShrink: 0,
          [`& .MuiDrawer-paper`]: {
            width: drawerOpen ? drawerWidth : 0,
            top: (theme) => theme.mixins.toolbar.minHeight,
            height: (theme) =>
              `calc(100% - ${theme.mixins.toolbar.minHeight}px)`,
            paddingTop: 0,
          },
        }}
      >
        <List>
          {navItems.map((item) => (
            <ListItemButton
              key={item.path}
              component={RouterLink}
              to={item.path}
              selected={location.pathname.startsWith(item.path)}
            >
              {item.icon}
              <ListItemText sx={{ ml: 1 }} primary={item.label} />
            </ListItemButton>
          ))}
        </List>
      </Drawer>
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
        }}
      >
        <Toolbar />
        <Outlet />
      </Box>
    </Box>
  );
};
