// POST /api/share — Request an upload slot, returns uploadUrl + publicUrl
export async function onRequestPost(context) {
  const { request, env } = context;

  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, PUT, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };

  try {
    const body = await request.json();
    const { contentType, size } = body;

    // Validate content type
    if (contentType !== 'video/webm') {
      return Response.json({ error: 'Invalid content type' }, {
        status: 400,
        headers: corsHeaders,
      });
    }

    // Validate file size (100MB limit)
    const maxSize = 100 * 1024 * 1024;
    if (!size || size <= 0 || size > maxSize) {
      return Response.json({ error: 'fileTooLarge' }, {
        status: 400,
        headers: corsHeaders,
      });
    }

    const uuid = crypto.randomUUID();
    const key = `shares/${uuid}.webm`;
    const publicDomain = env.SHARE_PUBLIC_DOMAIN || 'chronodrive-r2.tinyomnibus.me';
    const publicUrl = `https://${publicDomain}/${key}`;
    const expiresAt = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();

    return Response.json({
      uploadUrl: `/api/share/${uuid}`,
      publicUrl,
      expiresAt,
      key,
    }, {
      headers: corsHeaders,
    });
  } catch (err) {
    console.error('Share API error:', err);
    return Response.json({ error: 'Internal server error' }, {
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
      'Access-Control-Allow-Methods': 'POST, PUT, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    },
  });
}
