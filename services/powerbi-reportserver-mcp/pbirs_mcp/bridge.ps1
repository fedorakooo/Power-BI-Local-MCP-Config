$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
try {
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $base = $request.portal.TrimEnd('/') + '/api/v2.0/'
    $headers = @{}
    if ($request.traceparent) { $headers['traceparent'] = $request.traceparent }
    if ($request.session_id) { $headers['X-Session-Id'] = $request.session_id }
    $common = @{ UseDefaultCredentials = $true; TimeoutSec = 60; MaximumRedirection = 0; Headers = $headers }
    $credential = $null
    if ($request.credential_path) {
        $credential = Import-Clixml -LiteralPath $request.credential_path
        $common.Remove('UseDefaultCredentials')
        $common['Credential'] = $credential
    }
    switch ($request.operation) {
        'list' {
            $data = Invoke-RestMethod -Uri ($base + 'PowerBIReports?$select=Id,Name,Path,ModifiedDate') @common
            $result = @{ reports = @($data.value | Select-Object Id,Name,Path,ModifiedDate) }
        }
        'get' {
            $data = Invoke-RestMethod -Uri ($base + 'PowerBIReports(' + $request.report_id + ')') @common
            $result = @{ report = ($data | Select-Object Id,Name,Path,ModifiedDate) }
        }
        'download' {
            $uri = $base + 'PowerBIReports(' + $request.report_id + ')/Content/$value'
            Invoke-WebRequest -Uri $uri -OutFile $request.destination -UseBasicParsing @common
            $result = @{ downloaded = $true }
        }
        'upload' {
            # Resolve the current catalog object again. Destination is never provided by the LLM.
            $data = Invoke-RestMethod -Uri ($base + 'PowerBIReports(' + $request.report_id + ')') @common
            $folder = $data.Path.Substring(0, $data.Path.LastIndexOf('/'))
            if (!$folder) { $folder = '/' }
            if ([IO.Path]::GetFileNameWithoutExtension($request.source) -cne $data.Name) {
                throw 'Prepared file name must match the current report name.'
            }
            # Use the documented binary upload operation against the enrolled GUID.
            # Avoid the module's POST-create/409/PUT fallback and preserve all bytes.
            if ($data.Name -match '[\r\n"]') { throw 'Unsupported catalog name for multipart upload.' }
            $boundary = 'pbirs-' + [Guid]::NewGuid().ToString('N')
            $prefix = [Text.Encoding]::UTF8.GetBytes("--$boundary`r`nContent-Disposition: form-data; name=`"File`"; filename=`"$($data.Name).pbix`"`r`nContent-Type: application/octet-stream`r`n`r`n")
            $suffix = [Text.Encoding]::ASCII.GetBytes("`r`n--$boundary--`r`n")
            $bytes = [IO.File]::ReadAllBytes($request.source)
            $stream = New-Object IO.MemoryStream
            try {
                $stream.Write($prefix, 0, $prefix.Length)
                $stream.Write($bytes, 0, $bytes.Length)
                $stream.Write($suffix, 0, $suffix.Length)
                Invoke-WebRequest -Uri ($base + 'PowerBIReports(' + $request.report_id + ')/Model.Upload') -Method Post -Body $stream.ToArray() -ContentType ("multipart/form-data; boundary=$boundary") -UseBasicParsing @common | Out-Null
            } finally { $stream.Dispose() }
            $result = @{ uploaded = $true }
        }
        'create' {
            # POST is create-only. Never fall back to PUT/overwrite on conflict.
            $path = $request.folder.TrimEnd('/') + '/' + $request.name
            if ($request.name -match '[\\/:?*<>"\r\n]' -or !$request.folder.StartsWith('/')) { throw 'Unsafe destination' }
            $payload = @{'@odata.type'='#Model.PowerBIReport';Name=$request.name;Path=$path;
                Content=[Convert]::ToBase64String([IO.File]::ReadAllBytes($request.source));ContentType='';Description='Created by STAIR Power BI MCP'}
            $body = [Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Compress))
            $data = Invoke-RestMethod -Uri ($base + 'PowerBIReports') -Method Post -Body $body -ContentType 'application/json' @common
            $result = @{report=($data | Select-Object Id,Name,Path,ModifiedDate)}
        }
        default { throw 'Unsupported operation.' }
    }
    $result | ConvertTo-Json -Depth 8 -Compress
} catch {
    # Do not send upstream HTML, authentication headers, or report content to the model.
    $status = $null
    $code = $null
    $networkStatus = $null
    $failure = $_
    $exception = $failure.Exception
    $body = $failure.ErrorDetails.Message
    while ($exception) {
        if ($exception -is [Net.WebException]) { $networkStatus = $exception.Status.ToString() }
        if ($exception.Response) {
            $status = [int]$exception.Response.StatusCode
            try {
                $reader = New-Object IO.StreamReader($exception.Response.GetResponseStream())
                $responseBody = $reader.ReadToEnd()
                if ($responseBody) { $body = $responseBody }
                $reader.Dispose()
            } catch { }
        }
        $exception = $exception.InnerException
    }
    try {
        $upstream = $body | ConvertFrom-Json
        $candidate = [string]$upstream.error.code
        if ($candidate -match '^[a-zA-Z0-9_.-]{1,120}$') { $code = $candidate }
    } catch { }
    @{ error = 'Report Server operation failed'; exception_type = $failure.Exception.GetType().Name; http_status = $status; upstream_code = $code; network_status = $networkStatus } | ConvertTo-Json -Compress
    exit 1
}
