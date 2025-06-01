import asyncio

import discord
from cogwatch import watch
from discord.ext import commands

from actual_discord_bot.actual_connector import ActualConnector
from actual_discord_bot.bank_notifications import PekaoNotification
from actual_discord_bot.config import ActualConfig, DiscordConfig
from actual_discord_bot.errors import ParseNotificationError

REACTION_EMOJI = "✅"


class ActualDiscordBot(commands.Bot):
    def __init__(
        self,
        config: DiscordConfig,
        actual_connector: ActualConnector,
    ) -> None:
        self.channel_name = config.bank_notification_channel
        self.actual_connector = actual_connector

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.target_channel: discord.TextChannel | None = None

    @watch(path="actual_discord_bot")
    async def on_ready(self) -> None:
        for guild in self.guilds:
            channel = discord.utils.get(guild.channels, name=self.channel_name)
            if channel:
                self.target_channel = channel
                break
        if not self.target_channel:
            print(f"Warning: Could not find channel '{self.channel_name}'")

    async def create_actual_transaction(self, message: discord.Message) -> bool:
        try:
            notification = PekaoNotification.from_message(message.content)
            transaction_data = notification.to_transaction()
            self.actual_connector.save_transaction(transaction_data)
        except ParseNotificationError:
            print(
                f"ParseNotificationError: Could not parse message {message.id} with content: {message.content}",
            )
            return False
        except Exception as e:  # noqa: BLE001
            print(f"Exception occurred while processing message {message.id}: {e}")
            print(
                f"Error processing message {message.id} with content {message.content}: {e}",
            )
            return False
        else:
            return True

    async def handle_message(self, message: discord.Message) -> None:
        if await self.create_actual_transaction(message):
            await message.add_reaction(REACTION_EMOJI)

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return

        if self.target_channel and message.channel.id == self.target_channel.id:
            await self.handle_message(message)

    @commands.command(name="catch_up")
    async def catch_up(self, ctx: commands.Context) -> None:
        if not self.target_channel:
            await ctx.send(f"Error: Channel '{self.channel_name}' not found.")
            return

        async with ctx.typing():
            processed_count = 0
            async for message in self.target_channel.history(limit=None):
                for reaction in message.reactions:
                    if reaction.emoji == REACTION_EMOJI and reaction.me:
                        break
                else:
                    await self.handle_message(message)
                    processed_count += 1

        await ctx.send(f"Catch-up complete. Processed {processed_count} messages.")


async def main() -> None:
    discord_config = DiscordConfig.from_environ()
    actual_config = ActualConfig.from_environ()

    actual_connector = ActualConnector(actual_config)
    client = ActualDiscordBot(discord_config, actual_connector)
    await client.start(discord_config.token)


if __name__ == "__main__":
    asyncio.run(main())
