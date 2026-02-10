// PUT /api/share/:id — Upload video blob to R2
export async function onRequestPut(context) {
  const { request, env, params } = context;

  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'PUT, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };

  try {
    const id = params.id;

    // Validate UUID format
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(id)) {
      return Response.json({ error: 'Invalid ID' }, {
        status: 400,
        headers: corsHeaders,
      });
    }

    const contentType = request.headers.get('Content-Type') || 'video/webm';
    if (contentType !== 'video/webm') {
      return Response.json({ error: 'Invalid content type' }, {
        status: 400,
        headers: corsHeaders,
      });
    }

    // Check content length (100MB limit)
    const contentLength = parseInt(request.headers.get('Content-Length') || '0', 10);
    const maxSize = 100 * 1024 * 1024;
    if (contentLength > maxSize) {
      return Response.json({ error: 'fileTooLarge' }, {
        status: 400,
        headers: corsHeaders,
      });
    }

    const key = `shares/${id}.webm`;

    // Stream the request body directly to R2
    await env.SHARES_BUCKET.put(key, request.body, {
      httpMetadata: {
        contentType: 'video/webm',
      },
    });

    const publicDomain = env.SHARE_PUBLIC_DOMAIN || 'chronodrive-r2.tinyomnibus.me';
    const publicUrl = `https://${publicDomain}/${key}`;

    return Response.json({ success: true, publicUrl }, {
      headers: corsHeaders,
    });
  } catch (err) {
    console.error('Upload error:', err);
    return Response.json({ error: 'Upload failed' }, {
      status: 500,
      headers: corsHeaders,
    });
  }
}

export async function onRequestOptions() {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'PUT, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Content-Length',
    },
  });
}
