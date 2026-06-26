-- ============================================================
-- FILE: universal_subtitles.lua
-- Universal Subtitles Toolkit - VLC Integration
-- ============================================================

function descriptor()
    return {
        title = "Universal Subtitles AI",
        version = "1.0",
        author = "Joel S Raphael",
        url = "http://universalsubtitles.ai",
        shortdesc = "Launch Universal Subtitles AI",
        description = "Send the currently playing video directly to Universal Subtitles Toolkit to generate, translate, or sync.",
        capabilities = {"playing-listener"}
    }
end

function activate()
    create_dialog()
end

function deactivate()
    -- cleanup when closed
end

function close()
    vlc.deactivate()
end

function create_dialog()
    d = vlc.dialog("Universal Subtitles AI")
    d:add_label("<b>Universal Subtitle Toolkit</b>", 1, 1, 3, 1)
    d:add_label("Send this video to the toolkit to generate or translate subtitles.", 1, 2, 3, 1)
    d:add_button("Launch Subtitle Toolkit", click_open_app, 1, 3, 3, 1)
end

function click_open_app()
    local item = vlc.input.item()
    local video_path = ""
    
    -- Get the current video path from VLC
    if item then
        local uri = item:uri()
        if string.sub(uri, 1, 8) == "file:///" then
            video_path = vlc.strings.decode_uri(string.sub(uri, 9))
            video_path = string.gsub(video_path, "/", "\\") -- Windows path formatting
        end
    end

    -- Look for the installed Toolkit executable
    local local_appdata = os.getenv("LOCALAPPDATA")
    local roaming_appdata = os.getenv("APPDATA")
    local program_files = os.getenv("PROGRAMFILES")
    local program_files_x86 = os.getenv("PROGRAMFILES(X86)")

    -- Check all possible install locations Inno Setup might have used
    local exe_paths = {
        local_appdata .. "\\Programs\\UniversalSubtitleToolkit\\UniversalSubtitles.exe",
        roaming_appdata .. "\\Programs\\UniversalSubtitleToolkit\\UniversalSubtitles.exe",
        program_files .. "\\UniversalSubtitleToolkit\\UniversalSubtitles.exe",
        program_files_x86 .. "\\UniversalSubtitleToolkit\\UniversalSubtitles.exe"
    }

    local exe_path = ""
    for _, path in ipairs(exe_paths) do
        local f = io.open(path, "r")
        if f then
            f:close()
            exe_path = path
            break
        end
    end

    -- Launch the app
    if exe_path ~= "" then
        local cmd = ""
        if video_path ~= "" then
            -- Pass the video path to main.py's sys.argv[1]
            cmd = 'start "" "' .. exe_path .. '" "' .. video_path .. '"'
        else
            cmd = 'start "" "' .. exe_path .. '"'
        end
        os.execute(cmd)
        
        -- Close the VLC dialog box automatically
        vlc.deactivate()
    else
        d:add_label("<span style='color:red;'>Error: Could not find UniversalSubtitles.exe on this PC.</span>", 1, 4, 3, 1)
    end
end