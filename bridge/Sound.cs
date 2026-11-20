// 电脑的总音量开关（Windows 的 Core Audio）。只用到「静音 / 取消静音 / 现在是不是静音」。
using System.Runtime.InteropServices;

static class Sound
{
    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    class DeviceEnumerator { }

    [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IMMDeviceEnumerator
    {
        [PreserveSig] int EnumAudioEndpoints(int flow, int mask, out IntPtr devices);
        [PreserveSig] int GetDefaultAudioEndpoint(int flow, int role, out IMMDevice device);
    }

    [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IMMDevice
    {
        [PreserveSig] int Activate(ref Guid iid, int context, IntPtr options, [MarshalAs(UnmanagedType.IUnknown)] out object found);
    }

    [ComImport, Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioEndpointVolume
    {
        [PreserveSig] int RegisterControlChangeNotify(IntPtr notify);
        [PreserveSig] int UnregisterControlChangeNotify(IntPtr notify);
        [PreserveSig] int GetChannelCount(out uint count);
        [PreserveSig] int SetMasterVolumeLevel(float level, ref Guid context);
        [PreserveSig] int SetMasterVolumeLevelScalar(float level, ref Guid context);
        [PreserveSig] int GetMasterVolumeLevel(out float level);
        [PreserveSig] int GetMasterVolumeLevelScalar(out float level);
        [PreserveSig] int SetChannelVolumeLevel(uint channel, float level, ref Guid context);
        [PreserveSig] int SetChannelVolumeLevelScalar(uint channel, float level, ref Guid context);
        [PreserveSig] int GetChannelVolumeLevel(uint channel, out float level);
        [PreserveSig] int GetChannelVolumeLevelScalar(uint channel, out float level);
        [PreserveSig] int SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, ref Guid context);
        [PreserveSig] int GetMute([MarshalAs(UnmanagedType.Bool)] out bool mute);
    }

    static IAudioEndpointVolume Volume()
    {
        var enumerator = (IMMDeviceEnumerator)new DeviceEnumerator();
        int hr = enumerator.GetDefaultAudioEndpoint(0, 1, out IMMDevice device);      // 0=放声音的，1=多媒体
        if (hr != 0) throw new InvalidOperationException($"找不到放声音的设备 0x{hr:X}");
        Guid iid = typeof(IAudioEndpointVolume).GUID;
        hr = device.Activate(ref iid, 23, IntPtr.Zero, out object found);
        if (hr != 0) throw new InvalidOperationException($"打不开音量 0x{hr:X}");
        return (IAudioEndpointVolume)found;
    }

    public static bool IsMuted()
    {
        Volume().GetMute(out bool muted);
        return muted;
    }

    public static void Mute(bool on)
    {
        Guid none = Guid.Empty;
        int hr = Volume().SetMute(on, ref none);
        if (hr != 0) throw new InvalidOperationException($"0x{hr:X}");
    }
}
