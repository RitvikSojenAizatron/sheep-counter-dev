import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { visionApi } from '../api/visionApi';
import {
  Alert,
  Card,
  CardContent,
  Divider,
  FormControlLabel,
  IconButton,
  InputAdornment,
  List,
  ListItem,
  ListItemText,
  Stack,
  Switch,
  TextField,
  Typography,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import VisibilityIcon from '@mui/icons-material/Visibility';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import DeleteIcon from '@mui/icons-material/Delete';
import { useState } from 'react';
import { Camera, Line } from '../types/domain';

const emptyForm = {
  name: '',
  enabled: false,
  host: '',
  port: '554',
  username: '',
  password: '',
};

const parseRtspUrl = (url: string) => {
  const defaults = { host: url, port: '554', username: '', password: '' };
  try {
    const match = url.match(
      /^rtsp:\/\/(?:([^:@]*?)(?::([^@]*?))?@)?([^:/]+)(?::(\d+))?\/?(.*)$/,
    );
    if (!match) return defaults;
    const [, user, pass, host, port, path] = match;
    return {
      host: path ? `${host}/${path}` : host,
      port: port || '554',
      username: user ? decodeURIComponent(user) : '',
      password: pass ? decodeURIComponent(pass) : '',
    };
  } catch {
    return defaults;
  }
};

const buildRtspUrl = (
  host: string,
  port: string,
  username: string,
  password: string,
) => {
  const credentials =
    username || password
      ? `${encodeURIComponent(username)}:${encodeURIComponent(password)}@`
      : '';
  const portSuffix = port ? `:${port}` : '';
  return `rtsp://${credentials}${host}${portSuffix}`;
};

export const CamerasPage = () => {
  const queryClient = useQueryClient();

  const { data: cameras = [] } = useQuery({
    queryKey: ['cameras'],
    queryFn: visionApi.fetchCameras,
  });

  const { data: lines = [] } = useQuery({
    queryKey: ['lines'],
    queryFn: visionApi.fetchLines,
  });

  const [activeCamera, setActiveCamera] = useState<Camera | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [editError, setEditError] = useState('');

  const createMutation = useMutation({
    mutationFn: (payload: Camera) => visionApi.createCamera(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cameras'] }),
  });

  const updateMutation = useMutation({
    mutationFn: (payload: { id: string; data: Partial<Camera> }) =>
      visionApi.updateCamera(payload.id, payload.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cameras'] });
      setEditOpen(false);
    },
    onError: () => setEditError('Failed to save camera. Please try again.'),
  });

  const deleteCameraMutation = useMutation({
    mutationFn: (id: string) => visionApi.deleteCamera(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cameras'] });
      handleClose();
    },
  });

  const deleteLineMutation = useMutation({
    mutationFn: (id: string) => visionApi.deleteLine(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['lines'] }),
  });

  const handleOpenCreate = () => {
    setForm(emptyForm);
    setCreateOpen(true);
  };

  const handleSaveCreate = () => {
    createMutation.mutate({
      name: form.name,
      enabled: form.enabled,
      ipAddress: buildRtspUrl(form.host, form.port, form.username, form.password),
    } as Camera);
    setCreateOpen(false);
  };

  const handleOpenEdit = (camera: Camera) => {
    setActiveCamera(camera);
    const parsed = parseRtspUrl(camera.ipAddress);
    setForm({
      name: camera.name,
      enabled: camera.enabled,
      host: parsed.host,
      port: parsed.port,
      username: parsed.username,
      password: parsed.password,
    });
    setEditOpen(true);
  };

  const handleSaveEdit = () => {
    if (!activeCamera) return;
    setEditError('');
    updateMutation.mutate({
      id: activeCamera.id,
      data: {
        name: form.name,
        enabled: form.enabled,
        ipAddress: buildRtspUrl(form.host, form.port, form.username, form.password),
      },
    });
  };

  const handleClose = () => {
    setCreateOpen(false);
    setEditOpen(false);
    setActiveCamera(null);
    setEditError('');
  };

  const cameraLines = (lines as Line[]).filter(
    (line) => line.cameraId === activeCamera?.id,
  );

  const passwordField = (
    <TextField
      label="Password"
      type={showPassword ? 'text' : 'password'}
      value={form.password}
      onChange={(e) => setForm((prev) => ({ ...prev, password: e.target.value }))}
      fullWidth
      InputProps={{
        endAdornment: (
          <InputAdornment position="end">
            <IconButton
              onClick={() => setShowPassword((prev) => !prev)}
              edge="end"
              size="small"
            >
              {showPassword ? <VisibilityOffIcon /> : <VisibilityIcon />}
            </IconButton>
          </InputAdornment>
        ),
      }}
    />
  );

  const cameraFormFields = (
    <Stack spacing={2} mt={1}>
      <TextField
        label="Name"
        value={form.name}
        onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
        fullWidth
      />
      <Stack direction="row" spacing={2}>
        <TextField
          label="Host / IP"
          value={form.host}
          onChange={(e) => setForm((prev) => ({ ...prev, host: e.target.value }))}
          fullWidth
          placeholder="192.168.1.100"
        />
        <TextField
          label="Port"
          value={form.port}
          onChange={(e) => setForm((prev) => ({ ...prev, port: e.target.value }))}
          sx={{ width: 120 }}
          placeholder="554"
        />
      </Stack>
      <Stack direction="row" spacing={2}>
        <TextField
          label="Username"
          value={form.username}
          onChange={(e) =>
            setForm((prev) => ({ ...prev, username: e.target.value }))
          }
          fullWidth
        />
        {passwordField}
      </Stack>
      <FormControlLabel
        control={
          <Switch
            checked={form.enabled}
            onChange={(e) =>
              setForm((prev) => ({ ...prev, enabled: e.target.checked }))
            }
          />
        }
        label="Enabled"
      />
    </Stack>
  );

  const camera = (cameras as Camera[])[0] ?? null;

  return (
    <Stack spacing={2}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="h4">Camera</Typography>
        {!camera && (
          <IconButton
            color="primary"
            onClick={handleOpenCreate}
            aria-label="Add camera"
          >
            <AddIcon />
          </IconButton>
        )}
      </Stack>

      {!camera ? (
        <Typography color="text.secondary" textAlign="center" py={4}>
          No camera configured.
        </Typography>
      ) : (
        <Card onClick={() => handleOpenEdit(camera)} sx={{ cursor: 'pointer' }}>
          <CardContent>
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Typography variant="subtitle1">{camera.name}</Typography>
              <Typography color={camera.online ? 'success.main' : 'error.main'}>
                {camera.online ? 'Online' : 'Offline'}
              </Typography>
            </Stack>
          </CardContent>
        </Card>
      )}

      {/* Create Camera Dialog */}
      <Dialog open={createOpen} onClose={handleClose} fullWidth maxWidth="sm">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSaveCreate();
          }}
        >
          <DialogTitle>Create Camera</DialogTitle>
          <DialogContent>{cameraFormFields}</DialogContent>
          <DialogActions>
            <Button onClick={handleClose}>Cancel</Button>
            <Button
              type="submit"
              variant="contained"
              disabled={createMutation.isPending}
            >
              Create Camera
            </Button>
          </DialogActions>
        </form>
      </Dialog>

      {/* Edit Camera Dialog */}
      <Dialog open={editOpen} onClose={handleClose} fullWidth maxWidth="sm">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSaveEdit();
          }}
        >
          <DialogTitle>Edit Camera</DialogTitle>
          <DialogContent>
            {editError && (
              <Alert severity="error" sx={{ mb: 2 }}>
                {editError}
              </Alert>
            )}
            {cameraFormFields}
            <Divider sx={{ my: 2 }} />
            <Typography variant="subtitle1" gutterBottom>
              Lines
            </Typography>
            {cameraLines.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No lines configured. Add lines in the Live view.
              </Typography>
            ) : (
              <List disablePadding>
                {cameraLines.map((line) => (
                  <ListItem
                    key={line.id}
                    divider
                    secondaryAction={
                      <IconButton
                        edge="end"
                        color="error"
                        disabled={deleteLineMutation.isPending}
                        onClick={() => {
                          if (
                            window.confirm(`Delete line "${line.name}"?`)
                          ) {
                            deleteLineMutation.mutate(line.id!);
                          }
                        }}
                      >
                        <DeleteIcon />
                      </IconButton>
                    }
                  >
                    <ListItemText primary={line.name} />
                  </ListItem>
                ))}
              </List>
            )}
          </DialogContent>
          <DialogActions>
            {activeCamera && (
              <Button
                type="button"
                color="error"
                variant="outlined"
                onClick={() => {
                  if (
                    window.confirm(
                      'Delete this camera? This action cannot be undone.',
                    )
                  ) {
                    deleteCameraMutation.mutate(activeCamera.id);
                  }
                }}
                disabled={deleteCameraMutation.isPending}
                sx={{ mr: 'auto' }}
              >
                Delete Camera
              </Button>
            )}
            <Button onClick={handleClose}>Cancel</Button>
            <Button
              type="submit"
              variant="contained"
              disabled={updateMutation.isPending}
            >
              Save Changes
            </Button>
          </DialogActions>
        </form>
      </Dialog>
    </Stack>
  );
};
