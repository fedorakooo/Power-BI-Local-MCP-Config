"""Probe actual MCP over HTTP; optionally compile one reviewed source revision."""
import argparse
import asyncio
import json
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def data(result):
    if result.isError:
        raise RuntimeError(str(result.content))
    return result.structuredContent or json.loads(next(x.text for x in result.content if x.type == 'text'))


async def check(args):
    async with streamablehttp_client(args.url, timeout=180) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = [tool.name for tool in (await session.list_tools()).tools]
            if set(tools) != {'inspect_headless_report', 'build_headless_report',
                    'list_report_workspace', 'create_dynamic_report', 'update_dynamic_report'}:
                raise RuntimeError('Unexpected MCP inventory')
            inspected = data(await session.call_tool('inspect_headless_report', {'project': args.project}))
            result = {'status': 'mcp_http_verified', 'url': args.url, 'tools': tools, 'inspect': inspected}
            if args.build:
                rejected = await session.call_tool('build_headless_report', {
                    'project': args.project, 'expected_revision': '0' * 64})
                if not rejected.isError:
                    raise RuntimeError('Stale revision was accepted')
                result['stale_revision_rejected'] = True
                result['build'] = data(await session.call_tool('build_headless_report', {
                    'project': args.project, 'expected_revision': inspected['revision']}))
            if args.evidence:
                Path(args.evidence).write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--project', required=True)
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--evidence')
    asyncio.run(check(parser.parse_args()))
